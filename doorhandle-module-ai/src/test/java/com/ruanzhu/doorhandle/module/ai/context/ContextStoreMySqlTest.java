package com.ruanzhu.doorhandle.module.ai.context;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.testsupport.CompactContextMySqlFixture;
import io.agentscope.core.message.*;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.test.util.ReflectionTestUtils;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/** Production context adapter against the complete compact schema, with external authorization faked only. */
@EnabledIfSystemProperty(named="doorhandle.context.mysql.config",matches=".+")
class ContextStoreMySqlTest {
    private CompactContextMySqlFixture fixture;
    private JdbcTemplate jdbc;
    private DurableContextStore store;
    private AgentContextDataApi data;
    private ChildProvenanceReader children;
    private final AgentActor alice=new AgentActor(1,"alice",AgentActor.Role.INSPECTOR);
    private final AgentActor bob=new AgentActor(2,"bob",AgentActor.Role.INSPECTOR);
    private final AtomicBoolean revoked=new AtomicBoolean();

    @BeforeEach void setup()throws Exception{
        fixture=new CompactContextMySqlFixture("doorhandle.context.mysql.config","doorhandle_agent_verify_","ecsit_",false);
        jdbc=fixture.jdbc();
        jdbc.update("INSERT INTO users(id,username,password) VALUES(1,'alice','fixture'),(2,'bob','fixture')");
        jdbc.update("INSERT INTO chat_session(session_id,user_id,username,title) VALUES('live',1,'alice','Original'),('fork',1,'alice','Fork')");
        data=mock(AgentContextDataApi.class);children=mock(ChildProvenanceReader.class);
        doAnswer(inv->{AgentActor actor=inv.getArgument(0);String session=inv.getArgument(1);
            if(revoked.get()||actor.userId()!=1||!List.of("live","fork").contains(session))throw new SecurityException("fixture permission revoked");return null;
        }).when(data).authorize(any(),anyString(),anyList());
        when(data.pin(any(),anyString(),anyList())).thenAnswer(inv->{data.authorize(inv.getArgument(0),inv.getArgument(1),inv.getArgument(2));return List.copyOf(inv.<List<AgentContextDataApi.Source>>getArgument(2));});
        when(data.history(any(),anyString(),anyLong(),anyLong(),anyInt())).thenReturn(new AgentContextDataApi.History(0,List.of(),false));
        var beans=new DefaultListableBeanFactory();beans.registerSingleton("data",data);beans.registerSingleton("children",children);
        var dataProvider=beans.getBeanProvider(AgentContextDataApi.class);
        var childProvider=beans.getBeanProvider(ChildProvenanceReader.class);
        assertThat(dataProvider.getObject()).isSameAs(data);
        assertThat(childProvider.getObject()).isSameAs(children);
        store=new DurableContextStore(jdbc,new DataSourceTransactionManager(fixture.dataSource()),new ObjectMapper(),dataProvider);
        store.childReaders(childProvider);
        for(String property:List.of("workbenchEnabled","recoveryEnabled","filesEnabled","childrenEnabled","compactionEnabled","offloadEnabled"))ReflectionTestUtils.setField(store,property,true);
        store.validate();
    }
    @AfterEach void close()throws Exception{if(fixture!=null)fixture.close();}

    @Test void bootstrapCheckpointAndAuditRollbackTogetherAndRetryRetainsOriginalState(){
        var boot=store.bootstrap(alice,"live","main","task-1",List.of(new UserMessage("first")));
        assertThat(boot.ready()).isFalse();
        var replay=store.bootstrap(alice,"live","main","task-1",List.of(new UserMessage("changed input")));
        assertThat(replay.initial().get(0).getTextContent()).isEqualTo("first");
        assertThatThrownBy(()->store.initialized(alice,"live","main","task-1",()->{
            jdbc.update("UPDATE chat_session SET title='partial checkpoint' WHERE session_id='live'");throw new IllegalStateException("checkpoint failed");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT title FROM chat_session WHERE session_id='live'",String.class)).isEqualTo("Original");
        assertThat(store.bootstrap(alice,"live","main","task-1",List.of()).ready()).isFalse();
        store.initialized(alice,"live","main","task-1",()->jdbc.update("UPDATE chat_session SET title='checkpoint saved' WHERE session_id='live'"));
        assertThat(store.bootstrap(alice,"live","main","task-1",List.of()).ready()).isTrue();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='CONTEXT'",Integer.class)).isEqualTo(2);
    }

    @Test void summaryCasAndPermissionInvalidationKeepOriginalImmutableBytes(){
        var original=List.<Msg>of(new UserMessage("old private history "+"x".repeat(8000)));
        var summary=store.save(alice,"live","main","run-1",0,0,"a".repeat(64),"original summary",new UserMessage("short summary"),List.of(),original);
        assertThat(store.load(alice,"live","main").id()).isEqualTo(summary.id());
        assertThatThrownBy(()->store.save(alice,"live","main","run-2",0,0,"a".repeat(64),"racing summary",new UserMessage("racing"),List.of(),original)).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM content_revision WHERE asset_kind='CONTEXT_SUMMARY'",Integer.class)).isEqualTo(1);
        revoked.set(true);assertThat(store.load(alice,"live","main")).isNull();
        assertThat(jdbc.queryForObject("SELECT content_text FROM content_revision WHERE asset_kind='CONTEXT_SUMMARY'",String.class)).isEqualTo("original summary");
        assertThat(jdbc.queryForObject("SELECT lifecycle FROM content_asset WHERE asset_kind='CONTEXT_SUMMARY'",String.class)).isEqualTo("INVALIDATED");
        assertThat(store.revision(alice,"live","main")).isEqualTo(2);
    }

    @Test void offloadReplaysReceiptRejectsDifferentBytesAndRechecksCurrentPermission(){
        String key="b".repeat(64),text="private tool text "+"z".repeat(17000),sha=DurableContextStore.hash(text);
        store.recordSeed(alice,"live","main","task","run",List.of());
        store.recordResult(alice,"live","main","task","run",key,"read",java.util.Map.of(),ToolResultBlock.text("done"));
        when(data.saveContextFile(eq(alice),eq("live"),anyString(),eq(text))).thenReturn(new WorkbenchSessionApi.File("file-1","context.txt","text/plain",text.length(),sha,"context"));
        when(data.readContextFile(eq(alice),eq("live"),eq("file-1"),eq(sha),eq(0),eq(20))).thenReturn(new AgentContextDataApi.Slice(text.substring(0,20),0,20,false,sha));
        var first=store.offload(alice,"live","main",key,ToolResultBlock.text(text));
        assertThat(ContextProvenance.text(first)).contains("fileId=file-1");
        store.offload(alice,"live","main",key,ToolResultBlock.text(text));
        verify(data,times(1)).saveContextFile(eq(alice),eq("live"),anyString(),eq(text));
        assertThat(store.read(alice,"live","main","file-1",sha,0,20).sha256()).isEqualTo(sha);
        assertThatThrownBy(()->store.offload(alice,"live","main",key,ToolResultBlock.text(text+"changed"))).isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(()->store.read(bob,"live","main","file-1",sha,0,20)).isInstanceOf(SecurityException.class);
        revoked.set(true);assertThatThrownBy(()->store.read(alice,"live","main","file-1",sha,0,20)).isInstanceOf(SecurityException.class);
    }

    @Test void childSourceUsesNarrowCurrentIdentityAndFreezesOriginalOriginSnapshot(){
        when(children.find(1,"live","child-1")).thenReturn(Optional.of(new ChildProvenanceReader.ChildProvenance("child-1",1,"live","COMPLETED",1)));
        var child=List.of(new AgentContextDataApi.Source("CHILD","child-1",""));
        assertThatThrownBy(()->store.recordSeed(alice,"live","main","parent","run",child)).isInstanceOf(IllegalStateException.class);
        store.recordSeed(alice,"live","child:child-1","child-task","child-run",List.of());
        store.recordSeed(alice,"live","main","parent","run",child);
        var pinned=store.taskSources(alice,"live","parent");
        store.recordSeed(alice,"live","child:child-1","later-task","later-run",List.of(new AgentContextDataApi.Source("FILE","later-file","a".repeat(64))));
        assertThat(store.taskSources(alice,"live","parent")).isEqualTo(pinned).doesNotContain(new AgentContextDataApi.Source("FILE","later-file","a".repeat(64)));
        verify(children,atLeastOnce()).find(1,"live","child-1");
    }
}
