# FRDLY HELPER
Flask + MySQL + vanilla JS local-service booking platform.
## Run
1. `mysql -u root -p -e "CREATE DATABASE frdly_helper CHARACTER SET utf8mb4; CREATE USER 'frdly'@'localhost' IDENTIFIED BY '...'; GRANT ALL ON frdly_helper.* TO 'frdly'@'localhost';"`
2. `pip install -r requirements.txt`; copy `.env.example` to `.env` values into your environment (tables are created on first start; the admin is created from ADMIN_EMAIL/ADMIN_PASSWORD).
3. `python app.py` then open http://127.0.0.1:5000 (use two browsers/profiles for customer and provider).
## Test
`python tests/test_workflow.py` (uses SQLite, not MySQL, so it needs no server).
