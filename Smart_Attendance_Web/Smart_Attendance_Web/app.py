import os, io, base64, sqlite3, csv, re
from datetime import datetime, date
from functools import wraps
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
DB = DATA / 'attendance.db'
FACE_DIR = DATA / 'faces'
MODEL_DIR = DATA / 'models'
EXPORT_DIR = BASE / 'exports'
CASCADE_PATH = BASE / 'haarcascade_default.xml'
for p in (DATA, FACE_DIR, MODEL_DIR, EXPORT_DIR): p.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change-this-secret-before-deployment')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
ALLOWED = {'.jpg','.jpeg','.png'}
CONF_THRESHOLD = float(os.getenv('FACE_CONFIDENCE_THRESHOLD','60'))


def db():
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row; return conn

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher')), full_name TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY AUTOINCREMENT, student_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, email TEXT DEFAULT '', department TEXT DEFAULT '', semester TEXT DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, attendance_date TEXT NOT NULL, attendance_time TEXT NOT NULL, subject TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Present', marked_by TEXT DEFAULT '', UNIQUE(student_id, attendance_date, subject), FOREIGN KEY(student_id) REFERENCES students(id));
        CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL);
        ''')
        username=os.getenv('ADMIN_USERNAME','admin')
        if not c.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone():
            c.execute('INSERT INTO users(username,password_hash,role,full_name,created_at) VALUES(?,?,?,?,?)',(username,generate_password_hash(os.getenv('ADMIN_PASSWORD','ChangeMe123!')),'admin','System Administrator',datetime.now().isoformat(timespec='seconds')))

def audit(action, details=''):
    with db() as c: c.execute('INSERT INTO audit_logs(username,action,details,created_at) VALUES(?,?,?,?)',(session.get('username','system'),action,details,datetime.now().isoformat(timespec='seconds')))

def login_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get('user_id'): return redirect(url_for('login'))
        return fn(*a,**kw)
    return wrapped

def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if not session.get('user_id'): return redirect(url_for('login'))
            if session.get('role') not in roles: abort(403)
            return fn(*a,**kw)
        return wrapped
    return deco

def face_path(student_id): return FACE_DIR / str(student_id)
def load_cascade():
    path=str(CASCADE_PATH) if CASCADE_PATH.exists() else cv2.data.haarcascades+'haarcascade_frontalface_default.xml'
    cascade=cv2.CascadeClassifier(path)
    return None if cascade.empty() else cascade

def get_recognizer():
    if not hasattr(cv2,'face'): raise RuntimeError('Install opencv-contrib-python (not opencv-python) to enable LBPH recognition.')
    model=MODEL_DIR/'Trainer.yml'
    if not model.exists(): raise RuntimeError('No trained face model. Register face samples and train the model first.')
    recognizer=cv2.face.LBPHFaceRecognizer_create(); recognizer.read(str(model)); return recognizer

def mark_present(student_id, subject='General', marked_by='Face recognition'):
    now=datetime.now()
    with db() as c:
        c.execute('INSERT OR IGNORE INTO attendance(student_id,attendance_date,attendance_time,subject,status,marked_by) VALUES(?,?,?,?,?,?)',(student_id,now.strftime('%Y-%m-%d'),now.strftime('%H:%M:%S'),subject.strip() or 'General','Present',marked_by))
        return c.execute('SELECT changes()').fetchone()[0] == 1

@app.context_processor
def inject_globals(): return {'current_year':datetime.now().year}

@app.route('/')
def index(): return redirect(url_for('dashboard') if session.get('user_id') else url_for('login'))

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username','').strip(); password=request.form.get('password','')
        with db() as c: user=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if user and check_password_hash(user['password_hash'],password):
            session.clear(); session.update(user_id=user['id'],username=user['username'],role=user['role'],full_name=user['full_name'])
            audit('Login'); return redirect(url_for('dashboard'))
        flash('Incorrect username or password.','danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): audit('Logout'); session.clear(); return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    with db() as c:
        students=c.execute('SELECT COUNT(*) n FROM students').fetchone()['n']
        teachers=c.execute("SELECT COUNT(*) n FROM users WHERE role='teacher'").fetchone()['n']
        today=c.execute("SELECT COUNT(*) n FROM attendance WHERE attendance_date=? AND status='Present'",(date.today().isoformat(),)).fetchone()['n']
        recent=c.execute('SELECT a.*,s.student_code,s.name FROM attendance a JOIN students s ON s.id=a.student_id ORDER BY a.id DESC LIMIT 8').fetchall()
    return render_template('dashboard.html',students=students,teachers=teachers,today=today,recent=recent)

@app.route('/students',methods=['GET','POST'])
@login_required
def students():
    if request.method=='POST':
        code=request.form.get('student_code','').strip(); name=request.form.get('name','').strip()
        if not code or not name: flash('Student ID and name are required.','danger')
        else:
            try:
                with db() as c: c.execute('INSERT INTO students(student_code,name,email,department,semester,created_at) VALUES(?,?,?,?,?,?)',(code,name,request.form.get('email','').strip(),request.form.get('department','').strip(),request.form.get('semester','').strip(),datetime.now().isoformat(timespec='seconds')))
                audit('Student created',code); flash('Student added.','success')
            except sqlite3.IntegrityError: flash('That student ID already exists.','danger')
        return redirect(url_for('students'))
    q=request.args.get('q','').strip()
    with db() as c:
        rows=c.execute('SELECT s.*, (SELECT COUNT(*) FROM attendance a WHERE a.student_id=s.id AND a.status="Present") present_count FROM students s WHERE s.name LIKE ? OR s.student_code LIKE ? ORDER BY s.name',('%'+q+'%','%'+q+'%')).fetchall()
    return render_template('students.html',students=rows,q=q)

@app.route('/students/<int:sid>/edit',methods=['POST'])
@login_required
def edit_student(sid):
    try:
        with db() as c: c.execute('UPDATE students SET student_code=?,name=?,email=?,department=?,semester=? WHERE id=?',(request.form.get('student_code','').strip(),request.form.get('name','').strip(),request.form.get('email','').strip(),request.form.get('department','').strip(),request.form.get('semester','').strip(),sid))
        audit('Student modified',str(sid)); flash('Student updated.','success')
    except sqlite3.IntegrityError: flash('Student ID already belongs to another record.','danger')
    return redirect(url_for('students'))

@app.route('/students/<int:sid>/delete',methods=['POST'])
@roles_required('admin')
def delete_student(sid):
    with db() as c:
        c.execute('DELETE FROM attendance WHERE student_id=?',(sid,)); c.execute('DELETE FROM students WHERE id=?',(sid,))
    shutil_path=face_path(sid)
    if shutil_path.exists():
        import shutil; shutil.rmtree(shutil_path)
    audit('Student deleted',str(sid)); flash('Student and linked attendance/faces deleted.','success'); return redirect(url_for('students'))

@app.route('/teachers',methods=['GET','POST'])
@roles_required('admin')
def teachers():
    if request.method=='POST':
        username=request.form.get('username','').strip(); password=request.form.get('password',''); full_name=request.form.get('full_name','').strip()
        if len(password)<8: flash('Password must contain at least 8 characters.','danger')
        else:
            try:
                with db() as c: c.execute('INSERT INTO users(username,password_hash,role,full_name,created_at) VALUES(?,?,?,?,?)',(username,generate_password_hash(password),'teacher',full_name,datetime.now().isoformat(timespec='seconds')))
                audit('Teacher created',username); flash('Teacher account created.','success')
            except sqlite3.IntegrityError: flash('Username already exists.','danger')
        return redirect(url_for('teachers'))
    with db() as c: rows=c.execute("SELECT id,username,full_name,created_at FROM users WHERE role='teacher' ORDER BY full_name").fetchall()
    return render_template('teachers.html',teachers=rows)

@app.route('/teachers/<int:uid>/delete',methods=['POST'])
@roles_required('admin')
def delete_teacher(uid):
    with db() as c: c.execute("DELETE FROM users WHERE id=? AND role='teacher'",(uid,))
    audit('Teacher deleted',str(uid)); flash('Teacher account removed.','success'); return redirect(url_for('teachers'))

@app.route('/faces')
@login_required
def faces():
    with db() as c: rows=c.execute('SELECT * FROM students ORDER BY name').fetchall()
    return render_template('faces.html',students=rows)

@app.route('/faces/<int:sid>',methods=['POST'])
@login_required
def upload_face(sid):
    with db() as c: student=c.execute('SELECT * FROM students WHERE id=?',(sid,)).fetchone()
    if not student: abort(404)
    files=request.files.getlist('images')
    if not files or all(not f.filename for f in files): flash('Choose one or more face images.','danger'); return redirect(url_for('faces'))
    folder=face_path(sid); folder.mkdir(exist_ok=True); saved=0
    cascade=load_cascade()
    if cascade is None: flash('Face detector could not be loaded.','danger'); return redirect(url_for('faces'))
    for f in files:
        ext=Path(secure_filename(f.filename)).suffix.lower()
        if ext not in ALLOWED: continue
        raw=np.frombuffer(f.read(),np.uint8); image=cv2.imdecode(raw,cv2.IMREAD_COLOR)
        if image is None: continue
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY); detected=cascade.detectMultiScale(gray,1.2,5,minSize=(50,50))
        if len(detected)==0: continue
        x,y,w,h=max(detected,key=lambda r:r[2]*r[3]); crop=cv2.resize(gray[y:y+h,x:x+w],(200,200))
        cv2.imwrite(str(folder/f'{datetime.now().timestamp()}_{saved}.jpg'),crop); saved+=1
    audit('Face samples uploaded',f'{student["student_code"]}: {saved}')
    flash(f'{saved} face sample(s) saved. Train the model to use updated samples.' if saved else 'No face found in the uploaded images. Try a clear, front-facing photo.','success' if saved else 'warning')
    return redirect(url_for('faces'))

@app.route('/train',methods=['POST'])
@roles_required('admin')
def train():
    if not hasattr(cv2,'face'): flash('Face module missing. Install opencv-contrib-python.','danger'); return redirect(url_for('faces'))
    images=[]; labels=[]
    with db() as c: students=c.execute('SELECT id FROM students').fetchall()
    for s in students:
        folder=face_path(s['id'])
        if not folder.exists(): continue
        for path in folder.glob('*.jpg'):
            im=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
            if im is not None: images.append(cv2.resize(im,(200,200))); labels.append(s['id'])
    if not images: flash('Upload face samples for students first.','warning'); return redirect(url_for('faces'))
    model=cv2.face.LBPHFaceRecognizer_create(); model.train(images,np.array(labels,dtype=np.int32)); model.write(str(MODEL_DIR/'Trainer.yml'))
    audit('Face model trained',f'{len(images)} samples / {len(set(labels))} students'); flash(f'Model trained with {len(images)} face samples from {len(set(labels))} student(s).','success'); return redirect(url_for('faces'))

@app.route('/attendance')
@login_required
def attendance():
    day=request.args.get('date',date.today().isoformat()); subject=request.args.get('subject','')
    with db() as c:
        rows=c.execute('SELECT a.*,s.student_code,s.name FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.attendance_date=? AND (?="" OR a.subject=?) ORDER BY s.name',(day,subject,subject)).fetchall()
        subjects=c.execute('SELECT DISTINCT subject FROM attendance ORDER BY subject').fetchall()
        students=c.execute('SELECT id,student_code,name FROM students ORDER BY name').fetchall()
    return render_template('attendance.html',rows=rows,day=day,subject=subject,subjects=subjects,students=students)

@app.route('/attendance/manual',methods=['POST'])
@login_required
def manual_attendance():
    sid=request.form.get('student_id'); status=request.form.get('status','Present'); subject=request.form.get('subject','General').strip() or 'General'; day=request.form.get('attendance_date',date.today().isoformat())
    if status not in ('Present','Absent','Late'): status='Present'
    try:
        with db() as c:
            c.execute('INSERT INTO attendance(student_id,attendance_date,attendance_time,subject,status,marked_by) VALUES(?,?,?,?,?,?) ON CONFLICT(student_id,attendance_date,subject) DO UPDATE SET status=excluded.status,attendance_time=excluded.attendance_time,marked_by=excluded.marked_by',(int(sid),day,datetime.now().strftime('%H:%M:%S'),subject,status,session['username']))
        audit('Manual attendance',f'{sid} {day} {status}'); flash('Attendance saved.','success')
    except (ValueError,sqlite3.IntegrityError): flash('Please select a valid student.','danger')
    return redirect(url_for('attendance',date=day,subject=subject))

@app.route('/attendance/<int:aid>/delete',methods=['POST'])
@roles_required('admin')
def delete_attendance(aid):
    with db() as c: c.execute('DELETE FROM attendance WHERE id=?',(aid,))
    audit('Attendance record deleted',str(aid)); flash('Attendance record deleted.','success'); return redirect(url_for('attendance'))

@app.route('/export')
@login_required
def export_excel():
    start=request.args.get('start',date.today().isoformat()); end=request.args.get('end',date.today().isoformat())
    with db() as c: rows=c.execute('SELECT s.student_code,s.name,s.department,s.semester,a.attendance_date,a.attendance_time,a.subject,a.status,a.marked_by FROM attendance a JOIN students s ON s.id=a.student_id WHERE a.attendance_date BETWEEN ? AND ? ORDER BY a.attendance_date,s.name',(start,end)).fetchall()
    wb=Workbook(); ws=wb.active; ws.title='Attendance'
    headers=['Student ID','Student Name','Department','Semester','Date','Time','Subject','Status','Marked By']; ws.append(headers)
    for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='253B66'); cell.alignment=Alignment(horizontal='center')
    for r in rows: ws.append([r[k] for k in ['student_code','name','department','semester','attendance_date','attendance_time','subject','status','marked_by']])
    for col in ws.columns:
        letter=col[0].column_letter; ws.column_dimensions[letter].width=min(max(max(len(str(x.value or '')) for x in col)+2,12),30)
    ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
    output=io.BytesIO(); wb.save(output); output.seek(0)
    return send_file(output,as_attachment=True,download_name=f'attendance_{start}_to_{end}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/live')
@login_required
def live(): return render_template('live.html')

@app.route('/api/recognize',methods=['POST'])
@login_required
def api_recognize():
    payload=request.json or {}; data=payload.get('image','')
    try:
        encoded=data.split(',',1)[1] if ',' in data else data
        raw=base64.b64decode(encoded); frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if frame is None: return jsonify(error='Invalid camera frame'),400
        cascade=load_cascade(); gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); faces=cascade.detectMultiScale(gray,1.2,5,minSize=(60,60))
        if len(faces)==0: return jsonify(found=False,message='No face detected')
        recognizer=get_recognizer()
        with db() as c: students={r['id']:r for r in c.execute('SELECT * FROM students').fetchall()}
        results=[]
        for x,y,w,h in faces:
            face=cv2.resize(gray[y:y+h,x:x+w],(200,200)); fid,confidence=recognizer.predict(face)
            if confidence < CONF_THRESHOLD and fid in students:
                s=students[fid]; results.append({'student_id':fid,'code':s['student_code'],'name':s['name'],'confidence':round(max(0,100-confidence),1),'recognized':True})
                mark_present(fid,payload.get('subject','General'),session['username'])
            else: results.append({'name':'Unknown','recognized':False,'confidence':round(max(0,100-confidence),1)})
        return jsonify(found=True,results=results)
    except RuntimeError as e: return jsonify(error=str(e)),400
    except Exception as e: app.logger.exception('Recognition error'); return jsonify(error='Could not process this frame.'),500

@app.route('/audit')
@roles_required('admin')
def audit_page():
    with db() as c: rows=c.execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100').fetchall()
    return render_template('audit.html',logs=rows)

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this page.'),403
@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='The requested page was not found.'),404

init_db()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=os.getenv('FLASK_DEBUG')=='1')
