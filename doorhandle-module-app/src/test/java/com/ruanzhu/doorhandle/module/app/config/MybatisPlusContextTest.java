package com.ruanzhu.doorhandle.module.app.config;

import com.ruanzhu.doorhandle.framework.config.MybatisPlusConfig;

import com.baomidou.mybatisplus.autoconfigure.MybatisPlusAutoConfiguration;
import com.baomidou.mybatisplus.autoconfigure.ConfigurationCustomizer;
import com.baomidou.mybatisplus.autoconfigure.MybatisPlusPropertiesCustomizer;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.OptimisticLockerInnerInterceptor;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

import javax.sql.DataSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class MybatisPlusContextTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withConfiguration(AutoConfigurations.of(MybatisPlusAutoConfiguration.class))
            .withUserConfiguration(MybatisPlusConfig.class)
            .withBean(DataSource.class, () -> mock(DataSource.class));

    @Test
    void autoConfigurationCreatesOneSqlSessionFactoryAndOneInterceptor() {
        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).hasSingleBean(SqlSessionFactory.class);
            assertThat(context).hasSingleBean(MybatisPlusInterceptor.class);
            assertThat(context).hasSingleBean(DetectionTaskMapper.class);
            assertThat(context).doesNotHaveBean(ConfigurationCustomizer.class);
            assertThat(context).doesNotHaveBean(MybatisPlusPropertiesCustomizer.class);

            MybatisPlusInterceptor interceptor = context.getBean(MybatisPlusInterceptor.class);
            assertThat(interceptor.getInterceptors()).hasSize(2);
            assertThat(interceptor.getInterceptors().get(0)).isInstanceOf(PaginationInnerInterceptor.class);
            assertThat(interceptor.getInterceptors().get(1)).isInstanceOf(OptimisticLockerInnerInterceptor.class);
        });
    }
}
