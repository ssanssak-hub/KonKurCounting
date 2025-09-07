# Telegram Konkur Countdown Bot

This is a simple Telegram bot that provides a countdown to the Iranian Konkur (University Entrance Exam) for different fields of study.

## Features

*   Countdown to the exam for different fields:
    *   Experimental Sciences (تجربی) - Tir 12, 1405
    *   Arts (هنر) - Tir 12, 1405
    *   Mathematics (ریاضی) - Tir 11, 1405
    *   Humanities (انسانی) - Tir 11, 1405
*   Uses Jalali calendar for date calculations.
*   Provides a simple Telegram interface with a keyboard.
*   Easy to deploy on Render.com.

## Prerequisites

*   A Telegram bot token from BotFather.
*   A Render.com account (or any other platform that can host Python web applications).
*   Python 3.9 or higher (required for `zoneinfo`).
*   `tzdata` package (already included in requirements.txt).

## Setup

1.  Clone this repository.
2.  Create a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Create a `.env` file in the root directory (copy from `sample.env`) and fill in the values:
    *   `BOT_TOKEN`: Your Telegram bot token.
    *   `PUBLIC_URL`: The public URL of your Render app (e.g., `https://your-app-name.onrender.com`).  If deploying to Render, this will likely be set automatically as `RENDER_EXTERNAL_URL`.
    *   `WEBHOOK_SECRET` (Optional): A secret path for the webhook (recommended for security).  If not set, the bot token will be used in the webhook URL.
5.  **Important: DO NOT commit the `.env` file to a public repository!**

## Deployment to Render

1.  Create a new Web Service on Render.
2.  Connect your repository.
3.  Configure the following environment variables in Render:
    *   `BOT_TOKEN`: Your Telegram bot token.
    *   `PUBLIC_URL` (or `RENDER_EXTERNAL_URL`):  The public URL of your Render app. Render usually sets `RENDER_EXTERNAL_URL` automatically.  If not, or if you're not using Render, set `PUBLIC_URL`.
    *   `WEBHOOK_SECRET` (Optional):  A secret path for the webhook.
4.  Set the Build Command to:
    ```bash
    python -m pip install --upgrade pip setuptools wheel && python -m pip install --no-cache-dir -r requirements.txt
    ```
5.  Set the Start Command to:
    ```bash
    gunicorn main:app --bind 0.0.0.0:$PORT --workers 2
    ```
6.  Deploy your application.

## Setting the Webhook

After deploying, you need to set the Telegram webhook so that Telegram can send updates to your bot. There are two ways to do this:

### Method 1: Using the `/set_webhook` endpoint

1.  Visit the `/set_webhook` endpoint of your deployed application (e.g., `https://your-app-name.onrender.com/set_webhook`).
2.  This will trigger the bot to set the webhook with Telegram using the `PUBLIC_URL` and `WEBHOOK_PATH` configured in the environment variables.

### Method 2: Using `curl`

1.  Use the following `curl` command, replacing `<YOUR_BOT_TOKEN>` with your actual bot token and `<YOUR_WEBHOOK_URL>` with the URL of your webhook endpoint:

    ```bash
    curl -F "url=<YOUR_WEBHOOK_URL>" "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook"
    ```

    For example, if you set a `WEBHOOK_SECRET` of `my_secret`, the `<YOUR_WEBHOOK_URL>` would be `https://your-app-name.onrender.com/webhook/my_secret`.  If you did *not* set a `WEBHOOK_SECRET`, it would be  `https://your-app-name.onrender.com/webhook/<YOUR_BOT_TOKEN>`.

## Security Considerations

*   **Never hardcode your bot token in the code.** Always use environment variables.
*   **Protect your webhook endpoint.** Use a `WEBHOOK_SECRET` to prevent unauthorized access to your bot.
*   **Sanitize user input.** Be careful when handling user input to prevent injection attacks.

## Contributing

Contributions are welcome! Please submit a pull request with your changes.

## License

[MIT License](LICENSE)
