-- 本地演示账户（密码均为 123456，仅限开发环境）
INSERT INTO users (username, password, email, role)
VALUES
 ('inspector.demo', '$2b$12$PdCGX2zMfKOqh9Ja35FndO9Q2GWLdOOj6sDUNb9yXYF8qOtFVD0qm', 'inspector.demo@example.com', 'INSPECTOR'),
 ('inspector.demo2', '$2b$12$PdCGX2zMfKOqh9Ja35FndO9Q2GWLdOOj6sDUNb9yXYF8qOtFVD0qm', 'inspector.demo2@example.com', 'INSPECTOR'),
 ('supervisor.demo', '$2b$12$PdCGX2zMfKOqh9Ja35FndO9Q2GWLdOOj6sDUNb9yXYF8qOtFVD0qm', 'supervisor.demo@example.com', 'SUPERVISOR'),
 ('supervisor.demo2', '$2b$12$PdCGX2zMfKOqh9Ja35FndO9Q2GWLdOOj6sDUNb9yXYF8qOtFVD0qm', 'supervisor.demo2@example.com', 'SUPERVISOR')
ON DUPLICATE KEY UPDATE role = VALUES(role), password = VALUES(password);
