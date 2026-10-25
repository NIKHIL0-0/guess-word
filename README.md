# GuessWord

A Wordle-style five-letter word game built with Flask, PostgreSQL/Supabase, and vanilla JavaScript.

## Live app

[Play GuessWord](https://guess-word-livid.vercel.app/game)

## Features

- User registration and login
- Daily match limit
- No repeated answer words for the same user
- Colored Wordle-style feedback
- Fun mode after five unsuccessful guesses
- Answer reveal with permanent result display
- Rankings for normal-mode wins
- Admin reports for daily, user, and per-word activity

## Local setup

1. Create a virtual environment and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure the Supabase connection through environment variables:

   ```text
   DB_HOST
   DB_PORT
   DB_NAME
   DB_USER
   DB_PASSWORD
   FLASK_SECRET_KEY
   ```

3. Ensure the normalized Supabase tables are populated:

   ```text
   userinfo
   games
   guesses
   matches
   match_guesses
   ```

4. Run locally:

   ```bash
   python app.py
   ```

The application is configured for Vercel through `vercel.json`. Secrets belong in local environment variables or Vercel project settings and must not be committed.
