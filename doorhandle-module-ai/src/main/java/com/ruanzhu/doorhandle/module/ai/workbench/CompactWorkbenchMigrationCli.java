package com.ruanzhu.doorhandle.module.ai.workbench;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/** Explicit offline CLI, never a Spring bean or automatic application migration. */
public final class CompactWorkbenchMigrationCli {
    private CompactWorkbenchMigrationCli() {}

    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 4 || !"--config".equals(arguments[0]) || !"--output".equals(arguments[2])) {
            throw new IllegalArgumentException("Explicit --config and fresh --output are required");
        }
        if (!"Linux".equals(System.getProperty("os.name"))) {
            throw new SecurityException("Workbench migration executes only on ECS");
        }
        Path work = Path.of("").toRealPath().resolve("work");
        Path config = Path.of(arguments[1]);
        Path output = Path.of(arguments[3]);
        if (!config.isAbsolute() || !config.toRealPath().equals(config) || !config.startsWith(work)
                || Files.size(config) > 1048576 || !Files.getPosixFilePermissions(config).stream()
                .allMatch(permission -> permission.name().startsWith("OWNER_"))) {
            throw new SecurityException("The explicit private CLI configuration is not admitted");
        }
        if (!output.isAbsolute() || !output.getParent().toRealPath().equals(output.getParent())
                || !output.startsWith(work) || Files.exists(output)) {
            throw new SecurityException("Use a fresh receipt under this checkout/work");
        }
        ObjectMapper mapper = new ObjectMapper().findAndRegisterModules()
                .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
        JsonNode input = mapper.readTree(Files.readString(config, StandardCharsets.UTF_8));
        Set<String> fields = Set.of("version", "kind", "instanceId", "machineId", "sourceSchema", "targetSchema",
                "serverUuid", "sourceUtcOffset", "sourceCollations", "connection", "scope", "client");
        var found = new java.util.HashSet<String>(); input.fieldNames().forEachRemaining(found::add);
        if (!found.equals(fields) || input.path("version").asInt() != 1
                || !"doorhandle-workbench-migration-config".equals(input.path("kind").asText())) {
            throw new SecurityException("Unsupported workbench migration CLI configuration");
        }
        JsonNode connection = input.path("connection");
        var connectionFields = new java.util.HashSet<String>(); connection.fieldNames().forEachRemaining(connectionFields::add);
        int port = connection.path("port").asInt();
        if (!connectionFields.equals(Set.of("host", "port", "username", "password"))
                || port < 1 || port > 65535
                || !connection.path("username").asText().matches("[a-z_][a-z0-9_]{0,31}")
                || connection.path("password").asText().isBlank()) {
            throw new SecurityException("Explicit owned loopback migration connection required");
        }
        String host = connection.path("host").asText();
        String scope = input.path("scope").asText();
        if ("ecs-disposable-migration".equals(scope)) {
            if (!"127.0.0.1".equals(host) || port <= 1024 || port == 3306) {
                throw new SecurityException("Disposable migration requires its owned non-default loopback endpoint");
            }
        } else if (!"production-migration".equals(scope)) {
            throw new SecurityException("Explicit migration scope is required");
        }
        if (!"127.0.0.1".equals(host)) {
            JsonNode client = input.path("client");
            Path docker = Path.of(client.path("executable").asText());
            String container = client.path("containerId").asText();
            if (!"production-migration".equals(scope) || !"docker".equals(client.path("kind").asText())
                    || !docker.isAbsolute() || !docker.toRealPath().equals(docker)
                    || !container.matches("[a-f0-9]{64}") || !host.matches("[0-9.]+") || port != 3306) {
                throw new SecurityException("Production migration endpoint must belong to the admitted MySQL container");
            }
            Process inspected = new ProcessBuilder(docker.toString(), "inspect", container).start();
            if (!inspected.waitFor(15, java.util.concurrent.TimeUnit.SECONDS) || inspected.exitValue() != 0) {
                inspected.destroyForcibly(); throw new SecurityException("Cannot verify the production container endpoint");
            }
            byte[] raw = inspected.getInputStream().readNBytes(4194305);
            if (raw.length > 4194304) throw new SecurityException("Container metadata exceeds the reviewed limit");
            JsonNode node = mapper.readTree(raw).path(0);
            boolean endpoint = false;
            var networks = node.path("NetworkSettings").path("Networks").elements();
            while (networks.hasNext()) endpoint |= host.equals(networks.next().path("IPAddress").asText());
            if (!container.equals(node.path("Id").asText()) || !node.path("State").path("Running").asBoolean() || !endpoint) {
                throw new SecurityException("JDBC endpoint differs from the admitted live MySQL container");
            }
        }
        var collations = new LinkedHashMap<String,String>();
        input.path("sourceCollations").fields().forEachRemaining(entry -> collations.put(entry.getKey(), entry.getValue().asText()));
        var admission = new WorkbenchLegacyMigration.Admission(input.path("instanceId").asText(),
                input.path("machineId").asText(), input.path("sourceSchema").asText(), input.path("targetSchema").asText(),
                input.path("serverUuid").asText(), ZoneOffset.of(input.path("sourceUtcOffset").asText()), collations);
        String schema = admission.targetSchema();
        if (!schema.matches("doorhandle_compact_candidate_[a-f0-9]{10}")) {
            throw new SecurityException("A new compact candidate target is required");
        }
        var data = new DriverManagerDataSource();
        data.setDriverClassName("com.mysql.cj.jdbc.Driver");
        data.setUrl("jdbc:mysql://" + host + ":" + port + "/" + schema
                + "?sslMode=DISABLED&allowPublicKeyRetrieval=true&serverTimezone=UTC");
        data.setUsername(connection.path("username").asText()); data.setPassword(connection.path("password").asText());
        var migration = new WorkbenchLegacyMigration(new JdbcTemplate(data), new DataSourceTransactionManager(data), mapper);
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("schemaVersion", 1); result.put("kind", "doorhandle-workbench-migration");
        try {
            var copied = migration.copy(admission);
            var verified = migration.verifyCommitted(admission, copied);
            if (!verified.matches()) throw new IllegalStateException("Post-commit workbench verification differs");
            result.put("status", "VERIFIED"); result.put("copy", copied); result.put("verification", verified);
            Files.writeString(output, mapper.writeValueAsString(result) + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
            Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rw-------"));
            System.out.println("Workbench copy and post-commit verification completed; no application was started.");
        } catch (WorkbenchLegacyMigration.CommitOutcomeUnknown unknown) {
            result.put("status", "UNKNOWN_STOPPED"); result.put("candidate", unknown.candidate());
            Files.writeString(output, mapper.writeValueAsString(result) + "\n", StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW);
            Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rw-------"));
            throw new IllegalStateException("Workbench commit outcome unknown; preserve candidate and source, never replay automatically");
        }
    }
}
