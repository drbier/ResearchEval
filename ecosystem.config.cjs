module.exports = {
  apps: [
    {
      name: "fast",
      script: "venv/bin/python",
      args: "-m uvicorn src.api.server:app --host 127.0.0.1 --port 3008 --workers 2",
      cwd: "/var/www/fast",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "2G",
      env: {
        PORT: 3008,
        PYTHONPATH: ".",
        ENVIRONMENT: "production",
        GEMINI_APPRAISAL_THINKING_LEVEL: "medium",
        GEMINI_SEARCH_BASE_THINKING_LEVEL: "low"
      }
    }
  ]
};

