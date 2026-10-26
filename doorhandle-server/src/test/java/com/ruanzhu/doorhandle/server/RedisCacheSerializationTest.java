package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.framework.config.RedisCacheConfig;
import com.ruanzhu.doorhandle.framework.config.properties.AppRedisProperties;
import com.ruanzhu.doorhandle.module.device.entity.Device;
import com.ruanzhu.doorhandle.module.device.entity.DeviceCaptureAlert;
import com.ruanzhu.doorhandle.module.model.entity.ModelInfo;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.RedisSerializationContext.SerializationPair;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;

import java.math.BigDecimal;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.mock;

class RedisCacheSerializationTest {
    private final ObjectMapper httpMapper = Jackson2ObjectMapperBuilder.json().build();
    private final AppRedisProperties properties = new AppRedisProperties();
    private final org.springframework.data.redis.cache.RedisCacheManager manager =
            new RedisCacheConfig(properties, httpMapper).redisCacheManager(mock(RedisConnectionFactory.class));

    { manager.afterPropertiesSet(); }

    private org.springframework.data.redis.cache.RedisCacheConfiguration configuration(String cache) {
        var decorated = (org.springframework.cache.transaction.TransactionAwareCacheDecorator) manager.getCache(cache);
        return ((org.springframework.data.redis.cache.RedisCache) decorated.getTargetCache()).getCacheConfiguration();
    }

    private SerializationPair<Object> values(String cache) {
        return configuration(cache).getValueSerializationPair();
    }

    private Object roundTrip(String cache, Object value) {
        return values(cache).read(values(cache).write(value));
    }

    @Test
    void modelCacheHitRestoresDomainTypeDatesDecimalsAndNewFacts() throws Exception {
        var model = new ModelInfo();
        model.setModelId(105);
        model.setModelName("六分类检测");
        model.setUploadTime(LocalDateTime.of(2026, 10, 26, 10, 30));
        model.setTrainingCompletedAt(model.getUploadTime().minusDays(1));
        model.setTrainingImageCount(3200);
        model.setEvaluationImageCount(96);
        model.setNoDetectionImageCount(2);
        model.setMapScore(new BigDecimal("0.6774"));
        model.setInferenceFps(new BigDecimal("12.3456"));
        var restored = assertInstanceOf(ModelInfo.class, roundTrip("model", model));
        assertEquals(model, restored);
        assertEquals(model.getNoDetectionRate(), restored.getNoDetectionRate());
        // Cache typing must not modify the application's API mapper.
        assertFalse(httpMapper.writeValueAsString(model).contains("@class"));
    }

    @Test
    void deviceListsAndNestedStatsPreserveElementTypesAndLargeIds() {
        var device = new Device();
        device.setId(Long.MAX_VALUE);
        var devices = new ArrayList<>(List.of(device));
        var restored = assertInstanceOf(List.class, roundTrip("device", devices));
        assertEquals(Long.MAX_VALUE, assertInstanceOf(Device.class, restored.get(0)).getId());
        var stats = new LinkedHashMap<String, Object>();
        stats.put("total", Long.MAX_VALUE);
        stats.put("devices", devices);
        stats.put("zero", 0);
        stats.put("immutable", Map.of("devices", List.of(device), "zero", 0));
        var restoredStats = assertInstanceOf(Map.class, roundTrip("employee", stats));
        assertEquals(Long.MAX_VALUE, restoredStats.get("total"));
        assertEquals(0, restoredStats.get("zero"));
        assertEquals(stats.get("immutable"), restoredStats.get("immutable"));
        assertInstanceOf(Device.class, ((List<?>) restoredStats.get("devices")).get(0));
        assertEquals(Map.of("zero", 0), roundTrip("employee", Map.of("zero", 0)));
        assertEquals(List.of(device), roundTrip("device", List.of(device)));
    }

    @Test
    void alertPageRestoresRecordsAndPagination() {
        var alert = new DeviceCaptureAlert();
        alert.setId(17L);
        var page = new Page<DeviceCaptureAlert>(2, 10, 15);
        page.setRecords(new ArrayList<>(List.of(alert)));
        var restored = assertInstanceOf(Page.class, roundTrip("device", page));
        assertEquals(2, restored.getCurrent());
        assertEquals(15, restored.getTotal());
        assertEquals(17L, assertInstanceOf(DeviceCaptureAlert.class, restored.getRecords().get(0)).getId());
    }

    @Test
    void rejectsUnregisteredRuntimeTypesAndOldUntypedPayloads() {
        assertThrows(org.springframework.data.redis.serializer.SerializationException.class,
                () -> values("model").read(ByteBuffer.wrap(
                        "{\"@class\":\"java.io.File\",\"path\":\"untrusted\"}".getBytes(StandardCharsets.UTF_8))));
        assertThrows(org.springframework.data.redis.serializer.SerializationException.class,
                () -> values("model").read(ByteBuffer.wrap("{\"modelId\":105}".getBytes(StandardCharsets.UTF_8))));
    }

    @Test
    void newNamespaceKeepsLegacyKeysAndPerCacheExpirySeparate() {
        var config = configuration("model");
        assertEquals("doorhandlecatch:cache:v2:model::", config.getKeyPrefixFor("model"));
        assertEquals(properties.getCacheTtls().get("model"), config.getTtl());
        assertFalse(config.getAllowCacheNullValues());
        assertEquals(properties.getCacheTtls().get("device"), configuration("device").getTtl());
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "DOORHANDLE_CACHE_REDIS_TEST_HOST", matches = "127\\.0\\.0\\.1")
    void realRedisCacheHitRestoresModelWithoutTouchingApplicationKeys() {
        var standalone = new org.springframework.data.redis.connection.RedisStandaloneConfiguration(
                "127.0.0.1", Integer.parseInt(System.getenv().getOrDefault("DOORHANDLE_CACHE_REDIS_TEST_PORT", "6379")));
        standalone.setDatabase(Integer.parseInt(System.getenv().getOrDefault("DOORHANDLE_CACHE_REDIS_TEST_DATABASE", "0")));
        String password = System.getenv("DOORHANDLE_CACHE_REDIS_TEST_PASSWORD");
        if (password != null && !password.isBlank()) standalone.setPassword(password);
        var factory = new org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory(standalone);
        factory.afterPropertiesSet();
        var isolated = new AppRedisProperties();
        isolated.setKeyPrefix("doorhandlecatch:verify:" + java.util.UUID.randomUUID());
        isolated.getCacheTtls().put("model", java.time.Duration.ofSeconds(60));
        var caches = new RedisCacheConfig(isolated, httpMapper).redisCacheManager(factory);
        caches.afterPropertiesSet();
        var cache = caches.getCache("model");
        try {
            var model = new ModelInfo();
            model.setModelId(105);
            model.setTrainingImageCount(3200);
            model.setTrainingCompletedAt(LocalDateTime.of(2026, 10, 26, 10, 30));
            model.setInferenceFps(new BigDecimal("12.3456"));
            cache.put("metadata:105", model);
            assertEquals(model, cache.get("metadata:105", ModelInfo.class));
            assertEquals(model, cache.get("metadata:105", ModelInfo.class));
        } finally {
            try { cache.evict("metadata:105"); } finally { factory.destroy(); }
        }
    }
}
