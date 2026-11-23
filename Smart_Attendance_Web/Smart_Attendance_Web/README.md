# Smart Attendance — Python Web Application

A Flask-based browser application adapted from the supplied OpenCV LBPH Smart Attendance project. It provides role-based login, student and teacher management, face sample upload, LBPH model training, browser-camera recognition, manual attendance, Excel export, and admin audit logs.

## Features
- Admin and teacher login with hashed passwords and role-based permissions.
- Admin creates/deletes teacher accounts.
- Add, edit, search and delete students (deleting a student also deletes their face samples and attendance records).
- Upload multiple face images for each student; the server detects and crops the largest face.
- Train/retrain an OpenCV LBPH recognizer from saved face samples.
- Browser webcam attendance: the browser sends camera frames to the Flask server; recognized students are marked once per date and subject.
- Manual attendance with Present/Absent/Late statuses.
- Date/subject filters and downloadable Excel (.xlsx) reports.
- Admin audit log.

## 1. Run locally on macOS
Use Python 3.10 or 3.11 for best compatibility with OpenCV wheels. In Terminal, from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open http://127.0.0.1:5000. Initial admin credentials come from `.env.example`: `admin` / `ChangeThisPassword123!`. Change the password/environment values before sharing or deploying.

macOS may ask permission for camera access in the browser. Allow it. Browser camera access requires `localhost` or HTTPS.

## 2. First-time setup
1. Sign in as admin.
2. Add student records under **Students**.
3. Open **Face Samples**, upload several clear, front-facing photos for each student (one face per image, good lighting).
4. Select **Train / Retrain Model**.
5. Open **Live Attendance**, allow webcam access and enter the subject.
6. Check **Attendance** and download an Excel report.
7. Create teacher accounts under **Teachers**. Teachers can manage student face samples and mark/view attendance; only admins can delete student records, delete attendance entries, manage teachers, train the model, and view audit logs.

## 3. GitHub
GitHub stores the source code; it does not run this Python web app. Do not commit `.env`, the SQLite database, face photos, or trained model. These are excluded by `.gitignore`.

```bash
git init
git add .
git commit -m "Build Smart Attendance web application"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git push -u origin main
```

## 4. Deploy (Render example)
1. Push this folder to a GitHub repository.
2. In Render, create a **Blueprint** from the repository; it reads `render.yaml`.
3. Set `ADMIN_PASSWORD` to a strong secret when prompted.
4. Deploy and open the HTTPS URL.
5. Keep the persistent disk mounted at `/opt/render/project/src/data`; SQLite, face samples and model files are stored there.

The included Render configuration is a starter deployment recipe; verify the selected Python/OpenCV wheel compatibility in the host build logs. For multiple application instances or production-scale use, replace SQLite with PostgreSQL and use shared persistent object storage for face samples/model artifacts.

## Important limitations and privacy
- Face recognition is probabilistic. LBPH confidence is not a calibrated identity probability; test with your own lighting/camera and tune `FACE_CONFIDENCE_THRESHOLD` carefully. Provide a manual correction process.
- The live browser stream sends individual frames to the server for processing. It does not record video.
- Obtain informed consent before collecting biometric data, restrict access, define a retention/deletion policy, and follow applicable institutional and local privacy rules.
- This is an educational starter project, not a certified attendance or biometric security system.

## Troubleshooting
- **`cv2.face` missing:** ensure `opencv-contrib-python-headless` is installed and uninstall conflicting `opencv-python` packages from the same environment.
- **No face detected:** use a well-lit, front-facing photo with one visible face.
- **Camera unavailable:** allow camera permission; use localhost or HTTPS, not an insecure remote HTTP URL.
- **Unknown faces:** capture more varied samples and retrain. Lower LBPH distance threshold = stricter matching.
