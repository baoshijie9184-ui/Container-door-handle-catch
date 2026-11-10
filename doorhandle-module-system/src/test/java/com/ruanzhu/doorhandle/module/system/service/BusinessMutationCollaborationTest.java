package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessMutationParticipant;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots;
import com.ruanzhu.doorhandle.module.system.security.TenantPrincipal;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.mock.web.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.web.context.request.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/** Admitted ECS MySQL only: real row locks, receipt uniqueness and rollback evidence. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
class BusinessMutationCollaborationTest {
    static OperationsMySqlFixture fixture;static BusinessUserDirectory users;
    static final AtomicBoolean rejectAudit=new AtomicBoolean();
    AnnotationConfigApplicationContext context;JdbcTemplate jdbc;Mutations mutations;
    record Command(long id,String value,Long expectedVersion) { }
    @Configuration @EnableAspectJAutoProxy(proxyTargetClass=true) @EnableTransactionManagement
    static class Config {
        @Bean JdbcTemplate jdbc(){return fixture.target();}
        @Bean PlatformTransactionManager transactions(JdbcTemplate jdbc){return new DataSourceTransactionManager(jdbc.getDataSource());}
        @Bean BusinessMutationParticipant participant(JdbcTemplate jdbc){return new Participant(jdbc);}
        @Bean OperationsAuditApi audit(JdbcTemplate jdbc){
            var delegate=new OperationsAuditService(jdbc,users);
            return new OperationsAuditApi(){
                public void append(Event event){delegate.append(event);}
                public void appendChange(ChangeEvent event){if(rejectAudit.get())throw new IllegalStateException("audit unavailable");delegate.appendChange(event);}
            };
        }
        @Bean BusinessMutationAudit aspect(OperationsAuditApi audit,PlatformTransactionManager tx){return new BusinessMutationAudit(audit,users,tx);}
        @Bean Nested nested(JdbcTemplate jdbc){return new Nested(jdbc);}
        @Bean Mutations mutations(JdbcTemplate jdbc,Nested nested){return new Mutations(jdbc,nested);}
    }
    static class Participant implements BusinessMutationParticipant {
        private final JdbcMutationSnapshots snapshots;
        private static final JdbcMutationSnapshots.Mapping ROW=new JdbcMutationSnapshots.Mapping("RECORD","collaboration_record","id","version",List.of("value_text"),Set.of(),Set.of());
        Participant(JdbcTemplate jdbc){snapshots=new JdbcMutationSnapshots(jdbc);}
        public boolean supports(String domain,String action){return "DEVICE".equals(domain);}
        public String resourceId(String domain,String action,Object[] args,Object result){return Long.toString(((Command)args[0]).id());}
        public Snapshot capture(AgentActor actor,String domain,String action,String id,boolean lock){return snapshots.capture(ROW,id,lock);}
        public Snapshot advanceVersion(Snapshot before,Snapshot after){return snapshots.advance(ROW,before,after);}
        public Object digestInput(String action,Object[] args){return args[0];}
        public List<Snapshot> related(AgentActor actor,String domain,String action,String id,Object[] args,List<Snapshot> previous,boolean lock){return "COMPOUND".equals(action)?List.of(snapshots.capture(ROW,"2",lock)):List.of();}
    }
    static class Nested {
        final JdbcTemplate jdbc;Nested(JdbcTemplate jdbc){this.jdbc=jdbc;}
        @BusinessMutation(domain="DEVICE",action="NESTED")
        public void update(Command command){jdbc.update("UPDATE collaboration_record SET value_text=? WHERE id=?",command.value(),command.id());}
    }
    static class Mutations {
        final JdbcTemplate jdbc;final Nested nested;Mutations(JdbcTemplate jdbc,Nested nested){this.jdbc=jdbc;this.nested=nested;}
        @BusinessMutation(domain="DEVICE",action="UPDATE")
        public Map<String,Object> update(Command command){jdbc.update("UPDATE collaboration_record SET value_text=? WHERE id=?",command.value(),command.id());return new LinkedHashMap<>(Map.of("id",Long.toString(command.id()),"version","0","value",command.value()));}
        @BusinessMutation(domain="DEVICE",action="COMPOUND")
        public boolean compound(Command command){jdbc.update("UPDATE collaboration_record SET value_text=? WHERE id=?",command.value(),command.id());nested.update(new Command(2,command.value(),0L));return true;}
    }
    @BeforeEach void setup() throws Exception {
        fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();
        fixture.install("CREATE TABLE collaboration_record(id BIGINT PRIMARY KEY,version BIGINT NOT NULL DEFAULT 0,value_text VARCHAR(100));",";");
        jdbc.update("INSERT INTO collaboration_record VALUES(1,0,'old'),(2,0,'old')");
        users=mock(BusinessUserDirectory.class);for(long id:List.of(1L,2L)){
            var identity=new BusinessUserDirectory.Identity(id,"user"+id,true);
            when(users.current(id,"user"+id)).thenReturn(identity);when(users.lockCurrent(id,"user"+id)).thenReturn(identity);
        }
        rejectAudit.set(false);context=new AnnotationConfigApplicationContext();
        context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("collaboration",Map.of("operations.audit.enabled","true","collaboration.mutations.enabled","true")));
        context.register(Config.class);context.refresh();mutations=context.getBean(Mutations.class);request(1,"request-one");
    }
    @AfterEach void close() throws Exception {SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();if(context!=null)context.close();if(fixture!=null)fixture.close();}
    private MockHttpServletResponse request(long actor,String requestId){
        var principal=new TenantPrincipal(actor,"user"+actor,"",List.of());
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(principal,null,List.of()));
        var request=new MockHttpServletRequest();request.addHeader("X-Request-ID",requestId);var response=new MockHttpServletResponse();
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request,response));return response;
    }
    private int count(String table){return jdbc.queryForObject("SELECT COUNT(*) FROM "+table,Integer.class);}
    @Test void exactRetryReturnsOriginalResultRevisionAndAuditReceipt(){
        var firstHeaders=request(1,"same-request");var first=mutations.update(new Command(1,"new",0L));
        var replayHeaders=request(1,"same-request");var replay=mutations.update(new Command(1,"new",0L));
        assertThat(replay).isEqualTo(first).containsEntry("version","1");
        assertThat(replayHeaders.getHeader("X-Resource-Version")).isEqualTo("1");
        assertThat(replayHeaders.getHeader("X-Audit-ID")).isEqualTo(firstHeaders.getHeader("X-Audit-ID")).isNotBlank();
        assertThat(count("audit_event")).isEqualTo(1);assertThat(count("workflow_instance")).isEqualTo(1);
    }
    @Test void changedContentUnderSameRequestAndStaleVersionBothFailClosed(){
        mutations.update(new Command(1,"new",0L));
        assertThatThrownBy(()->mutations.update(new Command(1,"different",0L))).hasMessageContaining("不同内容");
        request(2,"second-user");assertThatThrownBy(()->mutations.update(new Command(1,"late",0L))).hasMessageContaining("其他用户修改");
        assertThat(jdbc.queryForObject("SELECT value_text FROM collaboration_record WHERE id=1",String.class)).isEqualTo("new");
        assertThat(count("audit_event")).isEqualTo(1);assertThat(count("workflow_instance")).isEqualTo(1);
    }
    @Test void auditFailureRollsBackBusinessRevisionAndCommandReceipt(){
        rejectAudit.set(true);assertThatThrownBy(()->mutations.update(new Command(1,"new",0L))).hasMessage("audit unavailable");
        assertThat(jdbc.queryForObject("SELECT version FROM collaboration_record WHERE id=1",Long.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT value_text FROM collaboration_record WHERE id=1",String.class)).isEqualTo("old");
        assertThat(count("audit_event")).isZero();assertThat(count("workflow_instance")).isZero();
    }
    @Test void nestedCompoundCommandRecordsEveryActualResourceOnce(){
        assertThat(mutations.compound(new Command(1,"new",0L))).isTrue();
        assertThat(count("workflow_instance")).isEqualTo(1);assertThat(count("audit_event")).isEqualTo(2);
        assertThat(jdbc.queryForList("SELECT action FROM audit_event",String.class)).containsOnly("COMPOUND");
        assertThat(jdbc.queryForList("SELECT version FROM collaboration_record",Long.class)).containsOnly(1L);
    }
    @Test void concurrentUsersEditingOneVersionHaveExactlyOneCommittedWinner() throws Exception {
        var barrier=new CyclicBarrier(2);var pool=Executors.newFixedThreadPool(2);
        try {
            var work=new ArrayList<Future<Boolean>>();
            for(long actor:List.of(1L,2L)){work.add(pool.submit(()->{
                request(actor,"concurrent-"+actor);
                try{barrier.await(10,TimeUnit.SECONDS);mutations.update(new Command(1,"user"+actor,0L));return true;}
                catch(com.ruanzhu.doorhandle.common.BusinessException conflict){assertThat(conflict.getCode()).isEqualTo(409);return false;}
                finally{SecurityContextHolder.clearContext();RequestContextHolder.resetRequestAttributes();}
            }));}
            assertThat(List.of(work.get(0).get(20,TimeUnit.SECONDS),work.get(1).get(20,TimeUnit.SECONDS))).containsExactlyInAnyOrder(true,false);
        } finally {pool.shutdownNow();}
        assertThat(count("audit_event")).isEqualTo(1);assertThat(count("workflow_instance")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT version FROM collaboration_record WHERE id=1",Long.class)).isEqualTo(1L);
    }
}
