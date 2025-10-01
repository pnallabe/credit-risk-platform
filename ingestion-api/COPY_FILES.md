# File Copy Reference

## Files to Copy from Claude Artifacts

Copy the content from each artifact into these files:

1. **src/main.py** ← "FastAPI Ingestion API - Main Application"
2. **src/models.py** ← "Pydantic Models - Data Validation"
3. **src/auth.py** ← "Authentication Module - JWT Verification"
4. **tests/test_main.py** ← "test_main.py - Unit Tests"
5. **tests/conftest.py** ← "conftest.py - Pytest Configuration"
6. **deployment/Dockerfile** ← "Dockerfile - Cloud Run Deployment"
7. **deployment/cloudbuild.yaml** ← "cloudbuild.yaml - CI/CD Pipeline"
8. **deployment/deploy.sh** ← "deploy.sh - Manual Deployment Script"
9. **requirements.txt** ← "requirements.txt - Python Dependencies"
10. **.env.example** ← ".env.example - Environment Configuration Template"
11. **.gitignore** ← ".gitignore - Git Ignore Rules"
12. **Makefile** ← "Makefile - Development Commands"
13. **setup.sh** ← "setup.sh - Quick Setup Script"
14. **README.md** ← "README.md - Foundation Documentation"
15. **docs/PROJECT_STRUCTURE.md** ← "PROJECT_STRUCTURE.md - Complete Overview"
16. **docs/QUICK_REFERENCE.md** ← "QUICK_REFERENCE.md - Command Cheat Sheet"
17. **examples/example_payloads.json** ← "example_payloads.json - Test Data"

## Quick Copy Method

1. Click on each artifact in Claude's response above
2. Click the copy icon (top right of artifact)
3. Paste into the corresponding file
4. Save and repeat for all files

## After Copying All Files

```bash
cd ingestion-api
./setup.sh
make run
```

Visit http://localhost:8080/docs to see the API documentation!
