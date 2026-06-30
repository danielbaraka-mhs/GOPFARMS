# GOP FARMS (Django)

This project is now set up as a Django site. The original static pages are rendered through a `farms` Django app:

- `/` renders the home page.
- `/categories/` renders the categories page.
- `/admin/` is available for Django admin after migrations and a superuser are created.

## Setup

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python manage.py migrate
python manage.py runserver
```

Then visit `http://127.0.0.1:8000/`.

## Project Layout

- `gopfarms/` contains the Django project settings and root URLs.
- `farms/` contains the app views, URLs, and tests.
- `templates/farms/` contains the converted HTML templates.
- `static/` is ready for local CSS, JavaScript, and image assets.
