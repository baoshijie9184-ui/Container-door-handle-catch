package com.ruanzhu.doorhandle.framework.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.OptimisticLockerInnerInterceptor;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * MyBatis-Plus配置类
 */
@Configuration
@MapperScan({
        "com.ruanzhu.doorhandle.module.system.mapper",
        "com.ruanzhu.doorhandle.module.infra.mapper",
        "com.ruanzhu.doorhandle.module.device.mapper",
        "com.ruanzhu.doorhandle.module.model.mapper",
        "com.ruanzhu.doorhandle.module.detection.mapper",
        "com.ruanzhu.doorhandle.module.app.mapper"
})
public class MybatisPlusConfig {
    
    /**
     * 配置MyBatis-Plus拦截器插件
     * 添加分页插件
     */
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        // 添加分页插件
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        interceptor.addInnerInterceptor(new OptimisticLockerInnerInterceptor());
        return interceptor;
    }
}
