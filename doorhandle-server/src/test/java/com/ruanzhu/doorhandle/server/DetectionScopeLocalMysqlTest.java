package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.module.detection.api.DetectionAgentReadApiImpl;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import io.github.cdimascio.dotenv.Dotenv;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;

/** 显式验证真实接口和 Agent SQL 的同一数据范围，只写 scope-fixture-* 样本。 */
@EnabledIfSystemProperty(named="detection.scope.local.mysql", matches="true")
class DetectionScopeLocalMysqlTest {
    @Test void verifiesOwnAssignedEnterpriseAndRevokedAssignment() throws Exception {
        Path root=Path.of(System.getProperty("agent.actions.project", ".."));
        var env=Dotenv.configure().directory(root.toAbsolutePath().toString()).load();
        String url=env.get("DB_URL");
        if (!url.matches("jdbc:mysql://(?:localhost|127\\.0\\.0\\.1):3306/doorhandledb\\?.+"))
            throw new IllegalArgumentException("仅允许当前本机 doorhandledb");
        var source=new DriverManagerDataSource(url, env.get("DB_USERNAME"),env.get("DB_PASSWORD"));
        var jdbc=new JdbcTemplate(source);
        var client=new RestTemplate(new org.springframework.http.client.JdkClientHttpRequestFactory(
                java.net.http.HttpClient.newBuilder().version(java.net.http.HttpClient.Version.HTTP_1_1)
                .proxy(new java.net.ProxySelector() {
                    public List<java.net.Proxy> select(java.net.URI uri){return List.of(java.net.Proxy.NO_PROXY);}
                    public void connectFailed(java.net.URI uri,java.net.SocketAddress address,java.io.IOException error){}
                }).build()));
        String base="http://127.0.0.1:8080", prefix="scope-fixture-"+UUID.randomUUID().toString().substring(0,8);
        String mine=prefix+"-mine", assigned=prefix+"-assigned", foreign=prefix+"-foreign";
        for (var row:List.of(List.of(mine,"inspector.demo","inspector.demo2"),
                List.of(assigned,"supervisor.demo","inspector.demo"), List.of(foreign,"inspector.demo2","inspector.demo2"))) {
            jdbc.update("INSERT INTO detection_task(task_id,status,flow_status,created_by,assignee,total_images,processed_images,created_at,updated_at) VALUES(?,'COMPLETED','DETECTED',?,?,0,0,NOW(),NOW())", row.get(0),row.get(1),row.get(2));
        }
        // Surefire 工作目录是 server 模块；后端启动脚本在项目根目录运行。
        Path imageBase=root.resolve(Optional.ofNullable(env.get("DETECTION_UPLOAD_DIR")).orElse("uploads/images")).toAbsolutePath().normalize();
        Path annotatedBase=root.resolve(Optional.ofNullable(env.get("DETECTION_ANNOTATED_DIR")).orElse("uploads/annotated")).toAbsolutePath().normalize();
        for(String id:List.of(mine,assigned,foreign)) {
            Path folder=imageBase.resolve(id);Files.createDirectories(folder);
            Files.writeString(folder.resolve("scope-sample.jpg"),"scope-fixture-image");
            Files.createDirectories(annotatedBase.resolve(id));
            Files.writeString(annotatedBase.resolve(id).resolve("scope-sample.jpg"),"scope-fixture-annotated");
            jdbc.update("UPDATE detection_task SET source_oss_prefix=? WHERE task_id=?",folder.toString(),id);
        }
        var staff=login(client,base,"inspector.demo");var staff2=login(client,base,"inspector.demo2");var boss=login(client,base,"supervisor.demo");
        for(var pair:List.of(Map.entry("inspector.demo",staff),Map.entry("inspector.demo2",staff2),Map.entry("supervisor.demo",boss))) {
            boolean supervisor=pair.getKey().startsWith("supervisor");
            long expected=supervisor ? jdbc.queryForObject("SELECT COUNT(*) FROM detection_task",Long.class)
                    : jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE created_by=? OR assignee=?",Long.class,pair.getKey(),pair.getKey());
            var page=data(client,base,"/api/detection/tasks?size=200",pair.getValue());
            assertThat(((Number)page.get("total")).longValue()).isEqualTo(expected);
            var legacy=data(client,base,"/api/detection-records?size=200",pair.getValue());
            assertThat(((Number)legacy.get("total")).longValue()).isEqualTo(expected);
            for (var row:(List<Map<String,Object>>) legacy.get("records")) {
                assertThat(supervisor || pair.getKey().equals(row.get("created_by")) || pair.getKey().equals(row.get("assignee"))).isTrue();
            }
            long completed=supervisor ? jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE status IN ('COMPLETED','PARTIAL_FAILED')",Long.class)
                    : jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE status IN ('COMPLETED','PARTIAL_FAILED') AND (created_by=? OR assignee=?)",Long.class,pair.getKey(),pair.getKey());
            var stats=data(client,base,"/api/dashboard/stats",pair.getValue());
            assertThat(((Number)stats.get("detectionCount")).longValue()).isEqualTo(completed);
            var checked=data(client,base,"/api/statistics/check-detection-records",pair.getValue());
            assertThat(((Number)checked.get("recordCount")).longValue()).isEqualTo(expected);
            for(String endpoint:List.of("/api/dashboard/detection-trend", "/api/dashboard/detection-distribution",
                    "/api/dashboard/region-stats", "/api/dashboard/model-stats", "/api/dashboard/quality-disposition-stats",
                    "/api/dashboard/quality-workload", "/api/statistics/detection-trend", "/api/statistics/detection-distribution")) {
                assertThat(get(client,base,endpoint,pair.getValue()).get("code")).isEqualTo(200);
            }
        }
        data(client,base,"/api/detection/tasks/"+mine,staff);
        data(client,base,"/api/detection/tasks/"+assigned,staff);
        for(String endpoint:List.of("/api/files/images/","/api/files/annotated/","/api/direct/images/","/api/direct/annotated/")) {
            var image=client.exchange(base+endpoint+assigned+"/scope-sample.jpg",HttpMethod.GET,new HttpEntity<>(staff),String.class);
            assertThat(image.getStatusCode().value()).isEqualTo(200);
            assertThat(image.getHeaders().getCacheControl()).contains("no-store");
            assertThatThrownBy(()->client.exchange(base+endpoint+foreign+"/scope-sample.jpg",HttpMethod.GET,new HttpEntity<>(staff),String.class))
                    .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        }
        assertThatThrownBy(()->client.exchange(base+"/api/files/annotated/"+foreign,HttpMethod.GET,new HttpEntity<>(staff),String.class))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        assertThatThrownBy(()->get(client,base,"/api/detection/tasks/"+foreign,staff))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        long foreignId=jdbc.queryForObject("SELECT id FROM detection_task WHERE task_id=?",Long.class,foreign);
        assertThatThrownBy(()->get(client,base,"/api/detection-records/detail?id="+foreignId,staff))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        data(client,base,"/api/detection/tasks/"+foreign,boss);
        var config=new MybatisConfiguration();config.addMapper(DetectionTaskMapper.class);
        var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(config);
        var api=new DetectionAgentReadApiImpl(new SqlSessionTemplate(factory.getObject()).getMapper(DetectionTaskMapper.class));
        var actor=new AgentActor(1,"inspector.demo",AgentActor.Role.INSPECTOR);
        assertThat(api.task(actor,assigned).taskId()).isEqualTo(assigned);
        assertThatThrownBy(()->api.task(actor,foreign)).isInstanceOf(SecurityException.class);
        jdbc.update("UPDATE detection_task SET assignee='inspector.demo2' WHERE task_id=?",assigned);
        assertThatThrownBy(()->get(client,base,"/api/detection/tasks/"+assigned,staff))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        assertThatThrownBy(()->api.task(actor,assigned)).isInstanceOf(SecurityException.class);
        assertThatThrownBy(()->client.exchange(base+"/api/files/images/"+assigned+"/scope-sample.jpg",HttpMethod.GET,new HttpEntity<>(staff),String.class))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        var report=Map.of("passed",true,"fixtureTaskIds",List.of(mine,assigned,foreign),"checks",List.of(
                "own-and-assigned", "enterprise-supervisor", "legacy-records", "detail-denied", "dashboard-counts",
                "statistics-counts", "all-chart-queries", "agent-sql", "local-files-and-aliases", "reassignment-revokes-access"));
        Files.writeString(root.resolve("work/task-scope-local-mysql.json"),new ObjectMapper().writerWithDefaultPrettyPrinter().writeValueAsString(report));
    }
    private static HttpHeaders login(RestTemplate client,String base,String username) {
        var response=client.postForEntity(base+"/api/auth/login",Map.of("username",username,"password","123456"),Map.class);
        assertThat(response.getBody().get("code")).isEqualTo(200);var headers=new HttpHeaders();
        headers.set(HttpHeaders.COOKIE,String.join("; ",response.getHeaders().get(HttpHeaders.SET_COOKIE).stream().map(cookie->cookie.split(";",2)[0]).toList()));
        return headers;
    }
    private static Map<?,?> get(RestTemplate client,String base,String path,HttpHeaders headers) {
        return client.exchange(base+path,HttpMethod.GET,new HttpEntity<>(headers),Map.class).getBody();
    }
    private static Map<?,?> data(RestTemplate client,String base,String path,HttpHeaders headers) {
        var response=get(client,base,path,headers);assertThat(response.get("code")).isEqualTo(200);
        return (Map<?,?>)response.get("data");
    }
}
