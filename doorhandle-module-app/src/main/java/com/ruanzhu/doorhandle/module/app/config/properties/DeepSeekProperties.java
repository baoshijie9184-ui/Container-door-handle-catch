package com.ruanzhu.doorhandle.module.app.config.properties;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Data
@Configuration
@ConfigurationProperties(prefix = "deepseek")
public class DeepSeekProperties {

    /** 是否启用 DeepSeek LLM，关闭后回退到关键字路由 */
    private boolean enabled = true;

    /** DeepSeek API Key (OpenAI 兼容) */
    private String apiKey;

    /** API 基础地址，默认官方地址 */
    private String baseUrl = "https://api.deepseek.com";

    /** 模型名称 */
    private String model = "deepseek-v4-flash";

    /** 路由/意图识别温度，建议低以保证一致性 */
    private double temperature = 0.3;

    /** 回复生成温度 */
    private double chatTemperature = 0.7;

    /** 最大 token 数 */
    private int maxTokens = 2048;

    /** 外部模型连接超时 */
    private int connectTimeoutMs = 3000;

    /** 外部模型读取超时 */
    private int readTimeoutMs = 12000;

    /** RAG 查询重写和 rerank 的读取超时，避免拖慢首字响应 */
    private int ragReadTimeoutMs = 2000;
}
