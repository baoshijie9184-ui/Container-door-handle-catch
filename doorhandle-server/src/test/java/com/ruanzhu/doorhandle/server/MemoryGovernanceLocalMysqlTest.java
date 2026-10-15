package com.ruanzhu.doorhandle.server;

import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.module.ai.agent.*;
import com.ruanzhu.doorhandle.module.ai.api.RoleAgentController;
import com.ruanzhu.doorhandle.module.ai.config.AgentScopeProperties;
import com.ruanzhu.doorhandle.module.ai.journal.JdbcAgentJournal;
import com.ruanzhu.doorhandle.module.ai.service.AgentScopeConversationService;
import com.ruanzhu.doorhandle.module.ai.tool.BusinessToolkitFactory;
import com.ruanzhu.doorhandle.module.app.config.properties.ChatAssistantProperties;
import com.ruanzhu.doorhandle.module.app.dto.chat.*;
import com.ruanzhu.doorhandle.module.app.mapper.*;
import com.ruanzhu.doorhandle.module.app.service.*;
import com.ruanzhu.doorhandle.module.app.service.impl.*;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import com.ruanzhu.doorhandle.module.system.security.*;
import io.agentscope.core.message.*;
import io.agentscope.core.model.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** Actual MySQL, Java HTTP bridge and Harness; memory store/model responses are scripted fixtures. */
@EnabledIfSystemProperty(named="agent.memory.local.mysql",matches="true")
class MemoryGovernanceLocalMysqlTest {
    @Test void ownedEditsUseActualMysqlAuditAndPrivateHttpBridge()throws Exception{
        var http=com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        try(var context=new AnnotationConfigApplicationContext(AgentCardsLocalMysqlTest.Config.class)){
            var json=context.getBean(ObjectMapper.class);var user=context.getBean(UserMapper.class).findByUsername("inspector.demo");
            var owner=new TenantContext(user.getId(),user.getUsername());var otherUser=context.getBean(UserMapper.class).findByUsername("supervisor.demo");var other=new TenantContext(otherUser.getId(),otherUser.getUsername());
            var settings=new MemoryPreferenceService(context.getBean(JdbcTemplate.class),context.getBean(DataSourceTransactionManager.class));
            var calls=new AtomicInteger();String id="edit-fixture-"+UUID.randomUUID(),key=UUID.randomUUID().toString();
            http.createContext("/memories/owned/update",exchange->{
                calls.incrementAndGet();var body=json.readTree(exchange.getRequestBody());
                assertThat(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token")).isEqualTo("fixture-edit-token");
                boolean owned=owner.mem0UserId().equals(body.path("user_id").asText());
                assertThat(body.path("app_id").asText()).isEqualTo("doorhandlecatch");
                byte[] bytes=json.writeValueAsBytes(owned?Map.of("code",200,"data",Map.of("updated",true)):Map.of("detail","unavailable"));
                exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(owned?200:404,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
            });http.start();
            var bridge=new Mem0Client(new SensitiveDataSanitizer(),settings);ReflectionTestUtils.setField(bridge,"enabled",true);ReflectionTestUtils.setField(bridge,"serviceUrl","http://127.0.0.1:"+http.getAddress().getPort());ReflectionTestUtils.setField(bridge,"bridgeToken","fixture-edit-token");
            var governance=new PersonalMemoryService(bridge,settings);var request=new MemoryDtos.Update(key,"a".repeat(64),"仅用于编辑审计验收的私人正文",true);
            assertThat(governance.update(owner,id,request).updated()).isTrue();assertThat(governance.update(owner,id,request).replayed()).isTrue();assertThat(calls).hasValue(1);
            assertThatThrownBy(()->governance.update(owner,id,new MemoryDtos.Update(key,request.expectedDigest(),"其他正文",true))).hasMessageContaining("409");
            assertThatThrownBy(()->governance.delete(owner,id,new MemoryDtos.Delete(key,request.expectedDigest(),true))).hasMessageContaining("409");
            assertThatThrownBy(()->governance.update(other,id,new MemoryDtos.Update(UUID.randomUUID().toString(),request.expectedDigest(),request.memory(),true))).hasMessageContaining("404");
            var audit=context.getBean(JdbcTemplate.class).queryForMap("SELECT action_name,outcome,content_digest FROM agent_memory_audit WHERE owner_user_id=? AND request_key=?",owner.userId(),key);
            assertThat(audit.get("action_name")).isEqualTo("UPDATE");assertThat(audit.get("outcome")).isEqualTo("SUCCEEDED");assertThat(audit.toString()).doesNotContain(request.memory());
            Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath().normalize();
            Files.writeString(root.resolve("work/memory-edit-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("actualMysql",true,"privateBridgeHttp",true,"successfulReplayDidNotRedispatch",true,"changedContentAndActionRejected",true,"foreignOwnerRejected",true,"memoryResponsesScripted",true,"paidModelsCalled",false,"passed",true)));
        }finally{http.stop(0);}
    }
    @Test void preferencesApplyToBothEntrypointsAndDeletionIsOwnedAuditedAndIdempotent()throws Exception{
        Path root=Path.of(System.getProperty("agent.report.project","..")).toAbsolutePath().normalize();
        var http=com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
        try(var context=new AnnotationConfigApplicationContext(AgentCardsLocalMysqlTest.Config.class)){
            var json=context.getBean(ObjectMapper.class);var user=context.getBean(UserMapper.class).findByUsername("inspector.demo");
            var owner=new TenantContext(user.getId(),user.getUsername());var actor=new AgentActor(owner.userId(),owner.username(),AgentActor.Role.INSPECTOR);
            var settings=new MemoryPreferenceService(context.getBean(JdbcTemplate.class),context.getBean(DataSourceTransactionManager.class));var original=settings.get(owner);
            var memoryId="memory-fixture-"+UUID.randomUUID();String digest="a".repeat(64),privateMemory="本人验收报告按周汇总";var deleted=new AtomicBoolean();var searches=new AtomicInteger();var additions=new AtomicInteger();
            http.createContext("/memories",exchange->{
                int status=200;Object response;var body=json.readTree(exchange.getRequestBody());String path=exchange.getRequestURI().getPath();
                if(!"fixture-local-token".equals(exchange.getRequestHeaders().getFirst("X-Doorhandle-Memory-Token"))){status=401;response=Map.of("detail","private bridge authentication required");}
                else if(!owner.mem0UserId().equals(body.path("user_id").asText())){status=404;response=Map.of("detail","unavailable");}
                else if(path.endsWith("/search")){searches.incrementAndGet();response=Map.of("code",200,"data",List.of(Map.of("id",memoryId,"memory",privateMemory)));}
                else if(path.endsWith("/add")){additions.incrementAndGet();response=Map.of("code",200,"data",Map.of());}
                else if(path.endsWith("/list")){response=Map.of("code",200,"data",Map.of("items",deleted.get()?List.of():List.of(new MemoryDtos.Item(memoryId,privateMemory,"fixture-source",null,null,digest)),"hasMore",false));}
                else if(!memoryId.equals(body.path("memory_id").asText())||deleted.get()){status=404;response=Map.of("detail","unavailable");}
                else if(!digest.equals(body.path("expected_digest").asText())){status=409;response=Map.of("detail","changed");}
                else {deleted.set(true);response=Map.of("code",200,"data",Map.of("deleted",true));}
                byte[] bytes=json.writeValueAsBytes(response);exchange.getResponseHeaders().set("Content-Type","application/json");exchange.sendResponseHeaders(status,bytes.length);exchange.getResponseBody().write(bytes);exchange.close();
            });http.start();
            var memory=new Mem0Client(new SensitiveDataSanitizer(),settings);ReflectionTestUtils.setField(memory,"enabled",true);ReflectionTestUtils.setField(memory,"serviceUrl","http://127.0.0.1:"+http.getAddress().getPort());ReflectionTestUtils.setField(memory,"bridgeToken","fixture-local-token");
            var governance=new PersonalMemoryService(memory,settings);var roles=List.of(new SimpleGrantedAuthority("ROLE_INSPECTOR"));var auth=new UsernamePasswordAuthenticationToken(new TenantPrincipal(owner.userId(),owner.username(),"",roles),null,roles);SecurityContextHolder.getContext().setAuthentication(auth);
            try{
                var preference=settings.change(owner,new MemoryDtos.ChangePreference(original.revision(),true,false));
                var sql=context.getBean(SqlSessionTemplate.class);var chatSettings=new ChatAssistantProperties();var sessions=new ChatSessionServiceImpl(sql.getMapper(ChatSessionMapper.class),sql.getMapper(ChatMessageMapper.class),sql.getMapper(ChatPendingActionMapper.class),chatSettings,json);String session=sessions.createSession(owner.username()).getSessionId();
                var model=mock(Model.class);when(model.getModelName()).thenReturn("scripted-memory-policy");var prompts=new ArrayList<String>();when(model.stream(anyList(),anyList(),any())).thenAnswer(inv->{List<Msg> messages=inv.getArgument(0);prompts.add(messages.stream().map(Msg::getTextContent).collect(java.util.stream.Collectors.joining("\n")));return reactor.core.publisher.Flux.just(ChatResponse.builder().content(List.of(TextBlock.builder().text("仅按已授权上下文回答").build())).build());});
                var ai=new AgentScopeProperties();ai.setWorkspace(root.resolve("work/memory-governance-sdk").toString());var factory=new RoleAgentFactory(ai,new BusinessToolkitFactory(mock(DetectionAgentReadApi.class),mock(ResourceAgentReadApi.class),mock(ModelAgentReadApi.class),json),id->model);var journal=context.getBean(JdbcAgentJournal.class);var engine=new AgentScopeConversationService(factory,new AgentRunRegistry(),ai,journal);
                var beans=new DefaultListableBeanFactory();beans.registerSingleton("engine",engine);var rag=mock(RagKnowledgeService.class);when(rag.retrieveContext(anyString())).thenReturn("");
                var chat=new AgentScopeChatServiceImpl(sessions,beans.getBeanProvider(AgentConversationApi.class),rag,memory,new org.springframework.core.task.SyncTaskExecutor(),chatSettings,json);
                var request=new ChatSendMessageRequest();request.setSessionId(session);request.setContent("主站读取偏好");chat.handleUserMessage(owner.username(),request);assertThat(prompts.get(0)).contains(privateMemory);assertThat(searches).hasValue(1);assertThat(additions).hasValue(0);
                settings.change(owner,new MemoryDtos.ChangePreference(preference.revision(),false,false));
                var mvc=MockMvcBuilders.standaloneSetup(new RoleAgentController(factory,chat)).build();String payload=json.writeValueAsString(Map.of("threadId",session,"runId",UUID.randomUUID().toString(),"messages",List.of(Map.of("id","m1","role","user","content","独立页面关闭记忆后回答"))));var result=mvc.perform(post("/agui/run").principal(auth).contentType("application/json").content(payload)).andExpect(request().asyncStarted()).andReturn();result.getAsyncResult(10000);mvc.perform(asyncDispatch(result)).andExpect(status().isOk());assertThat(prompts.get(1)).doesNotContain(privateMemory);assertThat(searches).hasValue(1);assertThat(additions).hasValue(0);
                assertThat(governance.list(owner,50).items()).hasSize(1);
                var command=new MemoryDtos.Delete(UUID.randomUUID().toString(),digest,true);assertThat(governance.delete(owner,memoryId,command).deleted()).isTrue();assertThat(governance.delete(owner,memoryId,command).replayed()).isTrue();assertThat(governance.list(owner,50).items()).isEmpty();
                assertThat(settings.audit(owner)).anySatisfy(row->{assertThat(row.action()).isEqualTo("DELETE");assertThat(row.memoryId()).isEqualTo(memoryId);assertThat(row.outcome()).isEqualTo("SUCCEEDED");});assertThat(settings.audit(owner).toString()).doesNotContain(privateMemory);
                var otherUser=context.getBean(UserMapper.class).findByUsername("supervisor.demo");var other=new TenantContext(otherUser.getId(),otherUser.getUsername());assertThatThrownBy(()->governance.delete(other,memoryId,new MemoryDtos.Delete(UUID.randomUUID().toString(),digest,true))).hasMessageContaining("404");
                Files.writeString(root.resolve("work/memory-governance-local-mysql.json"),json.writerWithDefaultPrettyPrinter().writeValueAsString(Map.of("actualMysqlAndNativeSdk",true,"privateBridgeHttpVerified",true,"memoryResponsesScripted",true,"paidModelsCalled",false,"modelCalls",2,"crossEntrySettingsVerified",true,"passed",true)));
            }finally{var current=settings.get(owner);settings.change(owner,new MemoryDtos.ChangePreference(current.revision(),original.readEnabled(),original.saveEnabled()));}
        }finally{http.stop(0);SecurityContextHolder.clearContext();}
    }
}
