# FRDLY HELPER

### Real-Time Local Service Availability and Booking Platform

FRDLY HELPER is a web-based local service availability and booking platform that connects customers with nearby service providers. It enables users to discover service professionals, submit service requests, manage bookings, receive cost estimates, and track service progress through a centralized platform.

The platform supports multiple service categories, including mechanics, electricians, plumbers, towing services, water suppliers, appliance repair, and other local services.

---

## Key Features

### Customer
- User registration and authentication.
- Browse and search service categories.
- Discover nearby service providers.
- Submit and manage service requests.
- Track booking status and provider location when available.
- View and approve or reject service estimates.
- Review completed services.

### Service Provider
- Provider registration and profile management.
- Manage availability status.
- Receive and manage incoming service requests.
- Accept or reject service requests.
- Update booking progress.
- Submit detailed service estimates.
- Manage active and completed bookings.

### Administrator
- Administrative dashboard.
- Customer and provider management.
- Monitor service requests and bookings.
- Provider verification and account management.
- View platform statistics and activity.

---

## Service Booking Workflow

1. Customer selects a service category.
2. Customer submits a service request with the required details.
3. Suitable service providers can receive and respond to the request.
4. Provider accepts the request and updates its progress.
5. Provider reaches the customer's location.
6. Provider submits a cost estimate.
7. Customer reviews and approves or rejects the estimate.
8. Service proceeds after approval.
9. Provider completes the service.
10. Customer can submit a review.

---

## Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML, CSS, JavaScript |
| Database | MySQL |
| Database Connectivity | PyMySQL |
| ORM / Database Layer | As implemented in the project |
| Testing | Python, SQLite |
| Version Control | Git, GitHub |

---

## Project Structure

```text
FRDLY-HELPER/
│
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
│
├── static/
│   └── index.html
│
└── tests/
    └── test_workflow.py
```

---

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/samansathyan94/FRDLY-HELPER.git
cd FRDLY-HELPER
```

### 2. Create a Virtual Environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure MySQL

Ensure MySQL Server is installed and running.

Create the database and application user using MySQL:

```sql
CREATE DATABASE frdly_helper
CHARACTER SET utf8mb4;

CREATE USER 'frdly'@'localhost'
IDENTIFIED BY 'YOUR_ACTUAL_PASSWORD';

GRANT ALL PRIVILEGES ON frdly_helper.*
TO 'frdly'@'localhost';

FLUSH PRIVILEGES;
```

Use a strong password instead of the example placeholder.

### 5. Configure Environment Variables

Copy `.env.example` to `.env`.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Update `.env` with your actual local configuration:

```env
DB_BACKEND=mysql
DB_HOST=localhost
DB_PORT=3306
DB_USER=frdly
DB_PASSWORD=YOUR_ACTUAL_PASSWORD
DB_NAME=frdly_helper

SECRET_KEY=YOUR_RANDOM_SECRET

ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=YOUR_ADMIN_PASSWORD
```

Keep `.env` private. Never commit actual credentials to GitHub.

### 6. Run the Application

```bash
python app.py
```

Open your browser:

```text
http://127.0.0.1:5000
```

Use separate browser profiles or sessions to test Customer and Service Provider workflows.

The application initializes its database tables on startup. The initial administrator account is configured through the administrator environment variables, subject to the application's existing initialization logic.

---

## Testing

Run the workflow test:

```bash
python tests/test_workflow.py
```

The workflow test uses SQLite and does not require a running MySQL server, according to the current test setup.

---

## Security

- Keep database credentials in environment variables.
- Do not commit `.env` files.
- Do not expose administrator credentials.
- Use strong passwords and secret keys.
- Enforce role-based access to protected functionality.

---

## Repository

GitHub: https://github.com/samansathyan94/FRDLY-HELPER

---

## Project Status

Development is ongoing. Features and integrations should be considered complete only after implementation and testing in the application.

---

**FRDLY HELPER – Connecting People with Local Services.**
