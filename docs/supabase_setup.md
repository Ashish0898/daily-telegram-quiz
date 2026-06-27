# Supabase Setup Guide for daily-telegram-quiz

To store quiz history, audit requests, and handle access control, you will configure your Supabase database. If you already set up Supabase for `daily-telegram-insights`, you can reuse the same project/credentials!

---

## 1. Create the Quiz History Table
This table logs all generated quiz questions, options, correct answers, and Telegram poll IDs.

Run this SQL block in your Supabase **SQL Editor**:

```sql
-- Create quiz_history table
create table if not exists quiz_history (
  id bigint generated always as identity primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  question text not null,
  options jsonb not null,                  -- JSON array of option strings (e.g. ["Paris", "Berlin"])
  correct_option_id integer not null,      -- 0-indexed correct answer (0, 1, 2, or 3)
  explanation text,                        -- Quiz explanation
  category text,                           -- Topic category (e.g., "Geography")
  poll_id text                             -- Telegram poll ID returned by API
);

-- Enable fast searching by category and date
create index if not exists idx_quiz_history_category_created_at 
on quiz_history (category, created_at desc);
```

---

## 2. Reusing or Creating allowed_users and request_audit
If you are using a **new Supabase project** for the Quiz Bot, run the following SQL scripts to set up user access and request logging:

### A. Allowed Users (Access Control Allowlist)
```sql
create table if not exists allowed_users (
  user_id bigint primary key,            -- Telegram User ID
  username text,                         -- Telegram username (for reference)
  role text default 'regular' check (role in ('admin', 'regular')),
  is_active boolean default true not null,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  added_by text default current_user
);

-- Example: Add your Telegram User ID as administrator (replace with actual ID)
insert into allowed_users (user_id, username, role, is_active) 
values (123456789, 'your_telegram_username', 'admin', true);
```

### B. Request Audit Logs
```sql
create table if not exists request_audit (
  id bigint generated always as identity primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  endpoint text not null,                -- 'webhook', 'quiz_scheduler'
  status text not null,                  -- 'success', 'error', 'access_denied'
  inserted_by text default current_user, 
  user_id bigint,                        -- Telegram user ID (if webhook)
  username text,                         -- Telegram username (if webhook)
  chat_id bigint,                        -- Telegram chat ID
  command text,                          -- Text or parameters run
  topic text,                            -- Category/theme of request
  response_content text,                 -- Response sent
  execution_time_ms integer, 
  error_message text
);

create index if not exists idx_request_audit_endpoint_created_at 
on request_audit (endpoint, created_at desc);
```

### C. User Quiz Answers (Track User Selections)
```sql
create table if not exists user_quiz_answers (
  id bigint generated always as identity primary key,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  poll_id text,                         -- Nullable, used for native Telegram polls
  quiz_id bigint,                       -- Nullable, references quiz_history.id for inline buttons
  user_id bigint not null,
  username text,
  selected_option_id integer not null,
  is_correct boolean,
  unique (poll_id, user_id),
  unique (quiz_id, user_id)
);

create index if not exists idx_user_quiz_answers_poll_id 
on user_quiz_answers (poll_id);

create index if not exists idx_user_quiz_answers_quiz_id 
on user_quiz_answers (quiz_id);

-- Create quiz_polls lookup table (scales individual DMs to store poll_id to quiz_id mappings)
create table if not exists quiz_polls (
  poll_id text primary key,
  quiz_id bigint references quiz_history(id) on delete cascade,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index if not exists idx_quiz_polls_quiz_id on quiz_polls (quiz_id);
```

---

## 3. Environment Variables
Add the following keys to your Vercel deployment and local `.env` file:
```env
SUPABASE_URL="https://your-project-id.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-secret-service-role-key"
```
