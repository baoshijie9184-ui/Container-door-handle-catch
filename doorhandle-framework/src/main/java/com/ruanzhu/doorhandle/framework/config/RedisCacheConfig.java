package com.ruanzhu.doorhandle.framework.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.databind.jsontype.BasicPolymorphicTypeValidator;
import com.ruanzhu.doorhandle.framework.config.properties.AppRedisProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.Jackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializationContext.SerializationPair;
import org.springframework.data.redis.serializer.StringRedisSerializer;

import java.util.LinkedHashMap;
import java.util.Map;

@Configuration
@EnableCaching
@RequiredArgsConstructor
public class RedisCacheConfig {

    private final AppRedisProperties redisProperties;
    private final ObjectMapper objectMapper;

    @Bean
    @ConditionalOnProperty(prefix = "app.redis", name = "enabled", havingValue = "true")
    public RedisCacheManager redisCacheManager(RedisConnectionFactory connectionFactory) {
        // Only this private cache mapper carries type metadata. HTTP JSON stays unchanged.
        var allowedTypes = BasicPolymorphicTypeValidator.builder()
                .allowIfSubType("com.ruanzhu.doorhandle.module.model.entity.")
                .allowIfSubType("com.ruanzhu.doorhandle.module.device.entity.")
                .allowIfSubType("com.baomidou.mybatisplus.extension.plugins.pagination.")
                .allowIfSubType(java.util.regex.Pattern.compile("java\\.util\\.(?:ArrayList|LinkedList|HashMap|LinkedHashMap|HashSet|LinkedHashSet|Arrays\\$ArrayList|ImmutableCollections\\$(?:List12|ListN|Map1|MapN|Set12|SetN)|Collections\\$(?:EmptyList|EmptyMap|EmptySet|SingletonList|SingletonMap|SingletonSet|UnmodifiableRandomAccessList|UnmodifiableList|UnmodifiableMap|UnmodifiableSet))"))
                .allowIfSubType(java.util.regex.Pattern.compile("java\\.time\\.(?:LocalDateTime|LocalDate|LocalTime|OffsetDateTime|Instant)"))
                .allowIfSubType(java.util.regex.Pattern.compile("java\\.math\\.(?:BigDecimal|BigInteger)"))
                .allowIfSubType(java.util.regex.Pattern.compile("java\\.lang\\.(?:String|Integer|Long|Double|Float|Short|Byte|Boolean)"))
                .build();
        ObjectMapper cacheMapper = objectMapper.copy().activateDefaultTyping(
                allowedTypes, ObjectMapper.DefaultTyping.EVERYTHING, JsonTypeInfo.As.PROPERTY);
        RedisCacheConfiguration defaultConfig = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(redisProperties.getDefaultTtl())
                .disableCachingNullValues()
                // Untyped legacy JSON cannot be restored as domain objects. Let old keys expire.
                .prefixCacheNameWith(redisProperties.getKeyPrefix() + ":cache:v2:")
                .serializeKeysWith(SerializationPair.fromSerializer(new StringRedisSerializer()))
                .serializeValuesWith(SerializationPair.fromSerializer(
                        // Read through Object so Jackson consumes the type envelope even for Map.of().
                        new Jackson2JsonRedisSerializer<>(cacheMapper, Object.class)));

        Map<String, RedisCacheConfiguration> cacheConfigurations = new LinkedHashMap<>();
        redisProperties.getCacheTtls().forEach((cacheName, ttl) ->
                cacheConfigurations.put(cacheName, defaultConfig.entryTtl(ttl)));

        return RedisCacheManager.builder(connectionFactory)
                .cacheDefaults(defaultConfig)
                .withInitialCacheConfigurations(cacheConfigurations)
                .transactionAware()
                .build();
    }
}
