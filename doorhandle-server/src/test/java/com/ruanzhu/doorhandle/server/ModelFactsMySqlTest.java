package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import com.ruanzhu.doorhandle.module.model.mapper.ModelInfoMapper;
import org.apache.ibatis.datasource.unpooled.UnpooledDataSource;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ScriptUtils;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.*;

/** Explicit, loopback-only disposable MySQL schema; never uses the application's DB_URL. */
@EnabledIfEnvironmentVariable(named = "DOORHANDLE_MODEL_FACTS_MYSQL_URL",
        matches = "jdbc:mysql://127\\.0\\.0\\.1:[0-9]+/doorhandle_model_facts_[a-z0-9]+(?:\\?.*)?")
class ModelFactsMySqlTest {
    @Test
    void migrationResumesAndMapperFactsSurviveLegacySqlAndRepeatedUpgrade() throws Exception {
        var source = new UnpooledDataSource("com.mysql.cj.jdbc.Driver",
                System.getenv("DOORHANDLE_MODEL_FACTS_MYSQL_URL"),
                System.getenv().getOrDefault("DOORHANDLE_MODEL_FACTS_MYSQL_USER", "root"),
                System.getenv().getOrDefault("DOORHANDLE_MODEL_FACTS_MYSQL_PASSWORD", ""));
        Path project = Path.of("..").toAbsolutePath().normalize();
        String schema = Files.readString(project.resolve("sql/mysql/schema.sql"));
        int start = schema.indexOf("CREATE TABLE IF NOT EXISTS `model_management`");
        assertTrue(start >= 0);
        String baseline = schema.substring(start, schema.indexOf(';', start) + 1);
        var migration = new ClassPathResource("db/migration-V62-detection-model-facts.sql");
        byte[] migrationBytes = migration.getContentAsByteArray();
        assertArrayEquals(Files.readAllBytes(project.resolve("sql/mysql/migration-V62-detection-model-facts.sql")), migrationBytes);

        try (var connection = source.getConnection()) {
            ScriptUtils.executeSqlScript(connection, new ByteArrayResource(baseline.getBytes(StandardCharsets.UTF_8)));
            try (var statement = connection.createStatement()) {
                statement.executeUpdate("INSERT INTO model_management(model_id,model_name,version,model_path) VALUES (7,'legacy','v1','legacy.onnx')");
                // Resume an interrupted additive migration, with just its first column present.
                statement.executeUpdate("ALTER TABLE model_management ADD COLUMN training_image_count INT NULL");
            }
            ScriptUtils.executeSqlScript(connection, migration);
            ScriptUtils.executeSqlScript(connection, migration);
        }

        var configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        var factory = new MybatisSqlSessionFactoryBean();
        factory.setDataSource(source);
        factory.setConfiguration(configuration);
        factory.setMapperLocations(new ClassPathResource("mapper/ModelInfoMapper.xml"));
        try (var session = factory.getObject().openSession(true)) {
            var mapper = session.getMapper(ModelInfoMapper.class);
            ModelInfo legacy = mapper.selectByModelId(7);
            assertNull(legacy.getTrainingImageCount());
            assertNull(legacy.getTrainingCompletedAt());
            assertNull(legacy.getInferenceFps());
            assertNull(legacy.getNoDetectionRate());

            var model = new ModelInfo();
            model.setModelId(105);
            model.setModelName("isolated-facts");
            model.setVersion("v62");
            model.setModelPath("isolated.onnx");
            model.setUploadTime(LocalDateTime.of(2026, 10, 26, 10, 30));
            model.setStatus("READY");
            model.setIsDefault(false);
            model.setUsageCount(0);
            model.setValidationStatus("PASSED");
            model.setMlopsStatus("EVALUATED");
            model.setDeploymentStrategy("FULL");
            model.setCanaryPercent(100);
            model.setTrainingImageCount(3200);
            model.setTrainingCompletedAt(model.getUploadTime().minusDays(1));
            model.setEvaluationImageCount(98);
            model.setNoDetectionImageCount(3);
            model.setMapScore(new BigDecimal("0.6774"));
            model.setInferenceFps(new BigDecimal("12.3456"));
            model.setCompatibilityNote("isolated CPU / 640 / batch 1 / inference only");
            assertEquals(1, mapper.insert(model));
            ModelInfo saved = mapper.selectByModelId(105);
            assertEquals(model, saved);
            assertEquals(new BigDecimal("0.03061224"), saved.getNoDetectionRate());
            assertEquals(2, mapper.selectAll().size());
            assertEquals(model, mapper.selectByModelNameAndVersion("isolated-facts", "v62"));

            // A rollback must keep added columns. An old application updates only old fields.
            try (var connection = source.getConnection(); var statement = connection.createStatement()) {
                assertEquals(1, statement.executeUpdate("UPDATE model_management SET update_description='legacy-client' WHERE model_id=105"));
                try (var row = statement.executeQuery("SELECT model_id,model_name,map_score FROM model_management WHERE model_id=105")) {
                    assertTrue(row.next());
                    assertEquals(model.getMapScore(), row.getBigDecimal("map_score"));
                }
                ScriptUtils.executeSqlScript(connection, migration);
            }
            session.clearCache();
            ModelInfo upgraded = mapper.selectByModelId(105);
            assertEquals(model.getTrainingImageCount(), upgraded.getTrainingImageCount());
            assertEquals(model.getTrainingCompletedAt(), upgraded.getTrainingCompletedAt());
            assertEquals(model.getInferenceFps(), upgraded.getInferenceFps());
            assertEquals("legacy-client", upgraded.getUpdateDescription());
            upgraded.setNoDetectionImageCount(0);
            assertEquals(1, mapper.updateModelRecord(upgraded));
            session.clearCache();
            assertEquals(BigDecimal.ZERO.setScale(8), mapper.selectByModelId(105).getNoDetectionRate());
        }
    }
}
