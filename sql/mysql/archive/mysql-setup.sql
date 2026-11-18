-- 修改MySQL服务器字符集配置
SET GLOBAL character_set_server = 'utf8mb4';
SET GLOBAL character_set_database = 'utf8mb4';
SET GLOBAL character_set_connection = 'utf8mb4';
SET GLOBAL character_set_results = 'utf8mb4';
SET GLOBAL character_set_client = 'utf8mb4';
SET GLOBAL collation_server = 'utf8mb4_unicode_ci';
SET GLOBAL collation_database = 'utf8mb4_unicode_ci';
SET GLOBAL collation_connection = 'utf8mb4_unicode_ci';

-- 显示当前字符集配置
SHOW VARIABLES LIKE 'character_set%';
SHOW VARIABLES LIKE 'collation%'; 