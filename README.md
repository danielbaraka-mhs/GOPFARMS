# GOP FARMS FastAPI App

## Environment Variables

Copy `.env.example` to `.env` and replace the placeholder values with your actual keys.

Required environment variables:

- `SUPABASE_URL`: Supabase project URL, e.g. `https://xyzcompany.supabase.co`
- `SUPABASE_ANON_KEY`: Supabase anon key for client access
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key for server operations
- `SUPABASE_DATABASE_URL`: Postgres connection string used by SQLAlchemy, e.g. `postgresql://user:pass@host:5432/dbname`
- `GOOGLE_CLIENT_ID`: Google OAuth client ID
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret
- `GOOGLE_OAUTH_REDIRECT_URI`: OAuth callback URL, default is `http://localhost:8000/oauth/callback/google`
- `SESSION_SECRET_KEY`: secret for session middleware

The app loads these values from environment variables using `python-dotenv`.

## Supabase Table Schema

Run this SQL in the Supabase SQL editor to create the tables used by the app:

```sql
create table if not exists users (
  id serial primary key,
  username varchar(150) not null unique,
  email varchar(254) not null unique,
  first_name varchar(150),
  last_name varchar(150),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists user_profiles (
  id serial primary key,
  user_id integer not null unique references users(id) on delete cascade,
  shop_name varchar(200),
  phone varchar(50),
  location varchar(200),
  city varchar(100),
  country varchar(100),
  payout_method varchar(100),
  avatar_url varchar(500),
  bio text,
  created_at timestamptz not null default now()
);

create table if not exists products (
  id serial primary key,
  seller_id integer not null references users(id) on delete cascade,
  title varchar(250) not null,
  description text,
  category varchar(100),
  emoji varchar(10),
  price numeric(12,2) not null default 0.00,
  unit varchar(50),
  quantity integer not null default 0,
  sold integer not null default 0,
  location varchar(255),
  image_url varchar(700),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists orders (
  id serial primary key,
  order_number varchar(80) not null unique,
  product_id integer references products(id) on delete set null,
  item_name varchar(250) not null,
  customer_name varchar(250) not null,
  amount numeric(12,2) not null default 0.00,
  status varchar(80) not null default 'Pending',
  created_at timestamptz not null default now()
);
```

## Using Google Auth Keys

Set your Google OAuth credentials in the `.env` file:

```env
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/oauth/callback/google
```

These values are loaded by `main.py` using `os.getenv(...)` after `python-dotenv` loads `.env`.

## Notes

- `SUPABASE_DATABASE_URL` is the Postgres URL that SQLAlchemy uses for its database connection.
- `SUPABASE_URL` and `SUPABASE_ANON_KEY` are used by the Supabase client for additional Supabase service access.
- If you do not want to use `.env`, set the same values in your OS environment variables instead.
