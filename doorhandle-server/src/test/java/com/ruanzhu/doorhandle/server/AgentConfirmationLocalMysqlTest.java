package com.ruanzhu.doorhandle.server;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.action.AgentActionService;
import com.ruanzhu.doorhandle.module.ai.config.*;
import com.ruanzhu.doorhandle.module.ai.journal.JdbcAgentJournal;
import com.ruanzhu.doorhandle.module.detection.api.DetectionAssignmentApiImpl;
import com.ruanzhu.doorhandle.module.detection.mapper.DetectionTaskMapper;
import com.ruanzhu.doorhandle.module.detection.service.DetectionTaskService;
import com.ruanzhu.doorhandle.module.system.api.AgentUserDirectoryImpl;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import io.github.cdimascio.dotenv.Dotenv;
import org.mybatis.spring.SqlSessionTemplate;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.http.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.*;
import org.springframework.web.client.RestTemplate;
import java.nio.file.*;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** 显式本机验证：只新增带标记的测试任务，保留数据；无需模型或检测 worker。 */
@EnabledIfSystemProperty(named="agent.actions.local.mysql",matches="true")
class AgentConfirmationLocalMysqlTest {
    @Test void validatesProductionConfirmationWithRealMysqlAndBackend() throws Exception {
        Path root=Path.of(System.getProperty("agent.actions.project",".."));
        var env=Dotenv.configure().directory(root.toAbsolutePath().toString()).load();
        String url=env.get("DB_URL");
        if (!url.startsWith("jdbc:mysql://localhost:3306/doorhandledb?")&&!url.startsWith("jdbc:mysql://127.0.0.1:3306/doorhandledb?"))
            throw new IllegalArgumentException("本验证仅允许当前本机 doorhandledb");
        var source=new DriverManagerDataSource(url,env.get("DB_USERNAME"),env.get("DB_PASSWORD"));
        var jdbc=new JdbcTemplate(source);var transactions=new DataSourceTransactionManager(source);
        var config=new MybatisConfiguration();config.addMapper(DetectionTaskMapper.class);config.addMapper(UserMapper.class);
        var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(config);
        var template=new SqlSessionTemplate(factory.getObject());
        var users=template.getMapper(UserMapper.class);var tasks=template.getMapper(DetectionTaskMapper.class);
        // 与 application.yml 的 HTTP/持久化 ObjectMapper 约定保持一致。
        var json=new ObjectMapper().findAndRegisterModules().disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
                .setSerializationInclusion(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL);
        var facade=new DetectionAssignmentApiImpl(tasks,mock(DetectionTaskService.class),new AgentUserDirectoryImpl(users),json);
        var journalSettings=new AgentJournalProperties();journalSettings.setEnabled(true);
        var journal=new JdbcAgentJournal(jdbc,transactions,json,journalSettings);journal.verifySchema();
        var settings=new AgentActionProperties();settings.setEnabled(true);
        var actions=new AgentActionService(jdbc,transactions,json,journal,facade,settings);actions.verifySchema();
        var boss=new AgentActor(users.findByUsername("supervisor.demo").getId(),"supervisor.demo",AgentActor.Role.SUPERVISOR);
        String suffix=UUID.randomUUID().toString().substring(0,8),sessionId="confirmation-fixture-"+suffix;
        var run=journal.begin(boss,sessionId,"supervisor-main","CHAT","fixture-"+suffix,"fixture-no-model-call");run.finish("COMPLETED");
        // HttpURLConnection 会丢弃 Origin 等受限请求头；联调必须实际发送来源头。
        var client=new RestTemplate(new org.springframework.http.client.JdkClientHttpRequestFactory(
                java.net.http.HttpClient.newBuilder().version(java.net.http.HttpClient.Version.HTTP_1_1)
                .proxy(new java.net.ProxySelector() {
                    public List<java.net.Proxy> select(java.net.URI uri){return List.of(java.net.Proxy.NO_PROXY);}
                    public void connectFailed(java.net.URI uri,java.net.SocketAddress address,java.io.IOException error){}
                }).build()));
        String base="http://127.0.0.1:8080";
        HttpHeaders owner=login(client,base,"supervisor.demo"),other=login(client,base,"supervisor.demo2"),staff=login(client,base,"inspector.demo");
        List<String> ids=new ArrayList<>();List<AgentActionService.View> pending=new ArrayList<>();
        for(String scenario:List.of("approve","reject","expired","changed","browser")) {
            String id="agent-confirm-fixture-"+scenario+"-"+suffix;ids.add(id);
            jdbc.update("INSERT INTO detection_task(task_id,status,flow_status,created_by,total_images,processed_images) VALUES(?,?,?,?,0,0)",id,"COMPLETED","DETECTED",boss.username());
            pending.add(actions.propose(boss,run.id(),"fixture-"+scenario,new DetectionAssignmentApi.Command(id,"本地测试质检站","inspector.demo","2026-11-01T15:30:00","确认联调固定样本")));
        }
        var a=pending.get(0);
        assertThat(get(client,base,owner,a.actionId()).get("status")).isEqualTo("PENDING");
        assertThatThrownBy(()->client.exchange(base+"/api/detection/tasks/"+ids.get(0)+"/assignment",HttpMethod.POST,
                new HttpEntity<>(Map.of("assignee","inspector.demo","qualityStation","绕过入口"),staff),Map.class))
                .isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        assertThatThrownBy(()->get(client,base,other,a.actionId())).isInstanceOf(org.springframework.web.client.HttpClientErrorException.NotFound.class);
        var emptyHeader=new HttpHeaders();emptyHeader.add(HttpHeaders.COOKIE,owner.getFirst(HttpHeaders.COOKIE));
        assertThatThrownBy(()->decide(client,base,emptyHeader,a,"APPROVE",Map.of())).isInstanceOf(org.springframework.web.client.HttpClientErrorException.BadRequest.class);
        assertThatThrownBy(()->decide(client,base,owner,a,"APPROVE",Map.of("assignee","supervisor.demo2"))).isInstanceOf(org.springframework.web.client.HttpClientErrorException.BadRequest.class);
        var foreign=new HttpHeaders();foreign.putAll(owner);foreign.set(HttpHeaders.ORIGIN,"https://foreign.invalid");
        assertThatThrownBy(()->decide(client,base,foreign,a,"APPROVE",Map.of())).isInstanceOf(org.springframework.web.client.HttpClientErrorException.Forbidden.class);
        assertThat(decide(client,base,owner,a,"APPROVE",Map.of()).get("status")).isEqualTo("SUCCEEDED");
        assertThat(decide(client,base,owner,a,"APPROVE",Map.of()).get("status")).isEqualTo("SUCCEEDED");
        assertThat(jdbc.queryForObject("SELECT assignee FROM detection_task WHERE task_id=?",String.class,ids.get(0))).isEqualTo("inspector.demo");
        assertThat(jdbc.queryForObject("SELECT DATE_FORMAT(due_at,'%Y-%m-%dT%H:%i:%s') FROM detection_task WHERE task_id=?",String.class,ids.get(0))).isEqualTo("2026-11-01T15:30:00");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM agent_action_audit WHERE action_id=? AND event_type='BUSINESS_CHANGED'",Integer.class,a.actionId())).isEqualTo(1);
        assertThat(decide(client,base,owner,pending.get(1),"REJECT",Map.of()).get("status")).isEqualTo("REJECTED");
        jdbc.update("UPDATE agent_pending_action SET expires_at=DATE_SUB(NOW(),INTERVAL 1 MINUTE) WHERE action_id=?",pending.get(2).actionId());
        assertThat(decide(client,base,owner,pending.get(2),"APPROVE",Map.of()).get("status")).isEqualTo("EXPIRED");
        jdbc.update("UPDATE detection_task SET quality_station='测试资源已变化' WHERE task_id=?",ids.get(3));
        assertThat(decide(client,base,owner,pending.get(3),"APPROVE",Map.of()).get("reasonCode")).isEqualTo("RESOURCE_CHANGED");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM detection_task WHERE task_id IN (?,?,?) AND assignee IS NOT NULL",Integer.class,ids.get(1),ids.get(2),ids.get(3))).isZero();
        var result=new LinkedHashMap<String,Object>();result.put("fixtureSession",sessionId);result.put("fixtureRun",run.id());result.put("fixtureTaskIds",ids);
        result.put("browserPendingAction",pending.get(4).actionId());result.put("confirmedAction",a.actionId());result.put("realMysqlAndBackendPassed",true);
        result.put("checks",List.of("approval","repeat-one-write","deadline","rejection","expiration","resource-change","other-owner","request-header","parameter-tampering","foreign-origin"));
        Files.writeString(root.resolve("work/stage-c-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(result));
    }
    private static HttpHeaders login(RestTemplate client,String base,String username) {
        var response=client.postForEntity(base+"/api/auth/login",Map.of("username",username,"password","123456"),Map.class);
        assertThat(response.getBody().get("code")).isEqualTo(200);var headers=new HttpHeaders();
        headers.set(HttpHeaders.COOKIE,String.join("; ",response.getHeaders().get(HttpHeaders.SET_COOKIE).stream().map(cookie->cookie.split(";",2)[0]).toList()));
        headers.set("X-Agent-Action","confirm");headers.set(HttpHeaders.ORIGIN,"http://127.0.0.1:3001");return headers;
    }
    private static Map<?,?> get(RestTemplate client,String base,HttpHeaders headers,String id) {return client.exchange(base+"/api/agent/actions/"+id,HttpMethod.GET,new HttpEntity<>(headers),Map.class).getBody();}
    private static Map<?,?> decide(RestTemplate client,String base,HttpHeaders headers,AgentActionService.View a,String decision,Map<String,Object> extra) {
        var body=new HashMap<>(extra);body.put("decision",decision);body.put("version",a.version());
        return client.exchange(base+"/api/agent/actions/"+a.actionId()+"/confirm",HttpMethod.POST,new HttpEntity<>(body,headers),Map.class).getBody();
    }
}
