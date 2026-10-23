# 🚀 CI/CD Pipeline Setup & User Guide

This guide explains how the **Continuous Integration (CI)** and **Continuous Deployment (CD)** pipelines work for the eSupport SEO platform using **GitHub Actions** and **Docker**.

---

## 📌 1. What is CI/CD? (CI/CD යනු කුමක්ද?)

- **CI (Continuous Integration)**: 
  ඔබ code එක Git හරහා GitHub එකට `push` කරන සෑම අවස්ථාවකදීම:
  1. Python 3.13 පරිසරය ස්වයංක්‍රීයව සකසයි (Setup Python environment).
  2. `requirements.txt` හි ඇති සියලුම packages install කරයි.
  3. Python code syntax හා compile errors පරීක්ෂා කරයි.
  4. Unit test suite එක සම්පූර්ණයෙන්ම run කර (53 tests) සියලුම tests pass වෙනවාදැයි තහවුරු කරයි.
  5. Database seeding smoke test එක run කරයි.
  6. Docker container image එක build කර image එකේ කිසිදු දෝෂයක් නැති බව පරීක්ෂා කරයි.
  - **වාසිය**: කිසියම් bug එකක් හෝ code එකක් බිඳී ඇත්නම් (broken code), GitHub Actions මඟින් වහාම රතු ලකුණකින් (Red cross ❌) පෙන්වා alert කරයි.

- **CD (Continuous Deployment)**:
  Code එක `main` branch එකට merge/push වූ වහාම:
  1. Production-ready Docker container image එකක් ස්වයංක්‍රීයව build කරයි.
  2. නොමිලේ GitHub Container Registry (GHCR) වෙත `ghcr.io/<username>/<repo>:latest` නමින් upload (push) කරයි.
  3. ඔබ cloud hosting එකක් (Render, Railway, VPS, ආදිය) භාවිතා කරන්නේ නම්, webhook මඟින් live server එක ස්වයංක්‍රීයව update කරයි.

---

## 📁 2. Created Files (සාදන ලද ගොනු)

| File | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Automatic testing, syntax check & Docker dry-run build on push/PR |
| `.github/workflows/deploy.yml` | Automatic Docker packaging to GHCR & cloud deployment webhook |
| `Dockerfile` | Production container setup with Python 3.13, Playwright Chromium & Uvicorn |
| `docker-compose.yml` | Local and production multi-container orchestration with persistent volumes |

---

## 🛠️ 3. How to Activate and Use (භාවිතා කරන්නේ කෙසේද?)

### Step 1: Push changes to GitHub
ටර්මිනල් එකේ පහත විධාන run කර GitHub එකට push කරන්න:

```bash
git add .
git commit -m "feat: setup GitHub Actions CI/CD pipeline and Docker configuration"
git push origin main
```

### Step 2: View Workflow in GitHub
1. ඔබේ GitHub repository එකට යන්න: `https://github.com/gunarathnayenuka-coder/x.ox`
2. උඩ tab bar එකේ ඇති **"Actions"** tab එක click කරන්න.
3. ඔබට **"CI Pipeline"** සහ **"CD Pipeline"** ස්වයංක්‍රීයව run වන ආකාරය සජීවීව දැකගත හැක:
   - ✅ **Green tick**: සියලුම tests pass වී ඇති අතර build එක සාර්ථකයි.
   - ❌ **Red cross**: කිසියම් test එකක් fail වී ඇත්නම් log එක click කර error එක බලාගත හැක.

---

## 🌐 4. Cloud Deployment Setup (Optional / කැමති නම්)

### Option A: Render.com (Recommended for Free / Easy hosting)
1. Render dashboard එකේ **New Web Service** සාදන්න.
2. Repo එක connect කරන්න හෝ Docker image එක තෝරන්න.
3. Settings හි ඇති **Deploy Hook** URL එක copy කරගන්න.
4. GitHub Repo එකේ **Settings** > **Secrets and variables** > **Actions** වෙත යන්න.
5. New repository secret එකක් සාදා:
   - Name: `RENDER_DEPLOY_HOOK_URL`
   - Value: `<Render Deploy Hook URL>`
6. දැන් ඔබ GitHub එකට `git push` කරන සෑම විටම Render server එක zero-downtime ස්වයංක්‍රීයව live deploy වේ!

### Option B: VPS (DigitalOcean / AWS / Hetzner / Contabo)
ඔබේ VPS එකේ docker ස්ථාපනය කර පහත විධානය මඟින් run කළ හැක:

```bash
docker compose up -d
```
Update කිරීමට:
```bash
docker compose pull && docker compose up -d
```
