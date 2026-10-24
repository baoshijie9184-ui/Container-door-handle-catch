package com.ruanzhu.doorhandle.module.system.service;

import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class OperationsAuditServiceTest {
    JdbcTemplate jdbc;BusinessUserDirectory users;OperationsAuditService service;
    AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR),bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR),boss=new AgentActor(3,"boss",AgentActor.Role.SUPERVISOR);
    @BeforeEach void setup(){jdbc=new JdbcTemplate(new DriverManagerDataSource("jdbc:h2:mem:"+UUID.randomUUID()+";MODE=MySQL;DB_CLOSE_DELAY=-1","sa",""));jdbc.execute("CREATE TABLE operations_audit(id BIGINT AUTO_INCREMENT PRIMARY KEY,actor_user_id BIGINT,scope VARCHAR(16),domain VARCHAR(48),action VARCHAR(64),resource_id VARCHAR(160),request_id VARCHAR(128),result VARCHAR(40),resource_version BIGINT,created_at TIMESTAMP, UNIQUE(actor_user_id,domain,action,resource_id,request_id,result))");users=mock(BusinessUserDirectory.class);for(var a:List.of(alice,bob,boss))when(users.current(a.userId(),a.username())).thenReturn(new BusinessUserDirectory.Identity(a.userId(),a.username(),a.supervisor()));service=new OperationsAuditService(jdbc,users);}
    OperationsAuditApi.Event event(AgentActor actor,String scope,String id){return new OperationsAuditApi.Event(actor,scope,"DETECTION","UPDATE",id,"request-1","APPLIED",1L);}
    @Test void supervisorCannotReadOtherAccountsPrivateAuditAndEmployeeOnlySeesOwn(){service.append(event(alice,"PRIVATE","a"));service.append(event(bob,"ENTERPRISE","b"));service.append(event(boss,"ENTERPRISE","c"));assertThat(service.list(alice,Long.MAX_VALUE,50,null)).hasSize(1);assertThat(service.list(boss,Long.MAX_VALUE,50,null)).hasSize(2).noneMatch(row->row.get("RESOURCE_ID").equals("a"));}
    @Test void exactReceiptIsIdempotentButChangingScopeUnderSameIdentityIsRejected(){var event=event(alice,"ENTERPRISE","a");service.append(event);service.append(event);assertThat(service.list(alice,Long.MAX_VALUE,50,null)).hasSize(1);assertThatThrownBy(()->service.append(event(alice,"PRIVATE","a"))).hasMessageContaining("冲突");}
    @Test void revokedIdentityAndFreeTextMetadataAreRejected(){when(users.current(alice.userId(),alice.username())).thenThrow(new SecurityException());assertThatThrownBy(()->service.append(event(alice,"PRIVATE","a"))).isInstanceOf(SecurityException.class);assertThatThrownBy(()->service.append(new OperationsAuditApi.Event(bob,"ENTERPRISE","DETECTION","WRITE","private prompt with spaces","r","DONE",null))).isInstanceOf(IllegalArgumentException.class);}
}
