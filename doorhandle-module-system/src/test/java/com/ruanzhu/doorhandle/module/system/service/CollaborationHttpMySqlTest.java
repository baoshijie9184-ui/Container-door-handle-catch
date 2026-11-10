package com.ruanzhu.doorhandle.module.system.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.extension.spring.MybatisSqlSessionFactoryBean;
import com.fasterxml.jackson.databind.*;
import com.ruanzhu.doorhandle.common.*;
import com.ruanzhu.doorhandle.contracts.agent.*;
import com.ruanzhu.doorhandle.contracts.collaboration.*;
import com.ruanzhu.doorhandle.contracts.organization.EmployeeDirectoryApi;
import com.ruanzhu.doorhandle.contracts.security.*;
import com.ruanzhu.doorhandle.framework.persistence.workflow.JdbcMutationSnapshots;
import com.ruanzhu.doorhandle.module.system.api.BusinessUserDirectoryImpl;
import com.ruanzhu.doorhandle.module.system.controller.*;
import com.ruanzhu.doorhandle.module.system.mapper.*;
import com.ruanzhu.doorhandle.module.system.realtime.*;
import com.ruanzhu.doorhandle.module.system.security.*;
import com.ruanzhu.doorhandle.module.system.service.impl.AuthServiceImpl;
import com.ruanzhu.doorhandle.module.system.support.OperationsMySqlFixture;
import com.ruanzhu.doorhandle.module.system.util.JwtUtil;
import jakarta.servlet.*;
import jakarta.servlet.DispatcherType;
import jakarta.servlet.http.*;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.junit.jupiter.api.parallel.*;
import org.mybatis.spring.SqlSessionTemplate;
import org.springframework.boot.Banner;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.autoconfigure.web.servlet.DispatcherServletRegistrationBean;
import org.springframework.boot.web.embedded.tomcat.TomcatServletWebServerFactory;
import org.springframework.boot.web.servlet.*;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.annotation.*;
import org.springframework.core.env.MapPropertySource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.security.authentication.*;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.*;
import org.springframework.transaction.support.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.DispatcherServlet;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.util.ContentCachingResponseWrapper;
import javax.sql.DataSource;
import java.io.*;
import java.net.*;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Predicate;
import static org.assertj.core.api.Assertions.*;

/** ECS only. Real loopback Tomcat, JDK CookieManager/HTTP streams and admitted MySQL; no Agent/Redis/Kafka/LLM context. */
@EnabledIfSystemProperty(named="doorhandle.operations.mysql.config",matches=".+")
@Execution(ExecutionMode.SAME_THREAD)
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class CollaborationHttpMySqlTest {
    static OperationsMySqlFixture fixture;
    static Path tomcatFiles;
    static final String SECRET="http-fixture-key-not-a-production-secret-0123456789",PASSWORD="http-fixture-password";
    ServletWebServerApplicationContext app;JdbcTemplate jdbc;URI base;long department;
    final ObjectMapper json=new ObjectMapper().findAndRegisterModules();
    final AtomicLong ids=new AtomicLong(1000);
    final List<Stream> streams=new CopyOnWriteArrayList<>();
    final List<CommitGate> responseGates=new CopyOnWriteArrayList<>();
    final ExecutorService clients=Executors.newCachedThreadPool(r->{var t=new Thread(r,"http-fixture-client");t.setDaemon(true);return t;});

    @Configuration @EnableWebMvc @EnableWebSecurity @EnableMethodSecurity
    @EnableTransactionManagement @EnableAspectJAutoProxy(proxyTargetClass=true)
    @Import({JwtUtil.class,LoginEligibilityService.class,LoginSessionService.class,UserDetailsServiceImpl.class,AuthServiceImpl.class,
            AuthController.class,LoginRateLimiter.class,JwtAuthenticationFilter.class,BusinessUserDirectoryImpl.class,
            AccountIdentityService.class,OrganizationBindingAuditStore.class,OperationsAuditService.class,BusinessMutationAudit.class,
            AccountAccessService.class,AccountAccessMutationParticipant.class,AccountAccessController.class,
            BusinessRealtimeService.class,BusinessRealtimeController.class,LoginSessionExceptionHandler.class,
            ResultHttpStatusAdvice.class,CollaborationConcurrencyExceptionHandler.class,AuthorizationExceptionHandler.class,GlobalExceptionHandler.class})
    static class HttpApp {
        @Bean TomcatServletWebServerFactory webServer()throws Exception{var server=new TomcatServletWebServerFactory(0);server.setAddress(InetAddress.getByName("127.0.0.1"));server.setBaseDirectory(tomcatFiles.toFile());return server;}
        @Bean DispatcherServlet dispatcherServlet(){return new DispatcherServlet();}
        @Bean DispatcherServletRegistrationBean dispatcher(DispatcherServlet servlet){var bean=new DispatcherServletRegistrationBean(servlet,"/");bean.setAsyncSupported(true);return bean;}
        @Bean DelegatingFilterProxyRegistrationBean securityRegistration(){var bean=new DelegatingFilterProxyRegistrationBean("springSecurityFilterChain");bean.setOrder(-100);bean.setAsyncSupported(true);return bean;}
        @Bean FilterRegistrationBean<JwtAuthenticationFilter> jwtRegistration(JwtAuthenticationFilter jwt){var bean=new FilterRegistrationBean<>(jwt);bean.setEnabled(false);return bean;}
        @Bean FilterRegistrationBean<ResponseGate> responseRegistration(){var bean=new FilterRegistrationBean<>(new ResponseGate());bean.setOrder(0);bean.addUrlPatterns("/api/auth/refresh","/api/auth/logout");return bean;}
        @Bean DataSource dataSource(){return fixture.dataSource();}
        @Bean JdbcTemplate jdbc(DataSource source){return new JdbcTemplate(source);}
        @Bean PlatformTransactionManager transactions(DataSource source){return new DataSourceTransactionManager(source);}
        @Bean ObjectMapper mapper(){return new ObjectMapper().findAndRegisterModules();}
        @Bean SqlSessionFactory sqlSessionFactory(DataSource source)throws Exception{var config=new MybatisConfiguration();config.setMapUnderscoreToCamelCase(true);config.addMapper(UserMapper.class);config.addMapper(AccountEmployeeBindingMapper.class);var factory=new MybatisSqlSessionFactoryBean();factory.setDataSource(source);factory.setConfiguration(config);return factory.getObject();}
        @Bean SqlSessionTemplate sqlSession(SqlSessionFactory factory){return new SqlSessionTemplate(factory);}
        @Bean UserMapper users(SqlSessionTemplate session){return session.getMapper(UserMapper.class);}
        @Bean AccountEmployeeBindingMapper bindings(SqlSessionTemplate session){return session.getMapper(AccountEmployeeBindingMapper.class);}
        @Bean EmployeeDirectoryApi personnel(JdbcTemplate jdbc){return new EmployeeDirectoryApi(){
            public List<EmployeeIdentity> findAll(Collection<Long> ids){var result=new ArrayList<EmployeeIdentity>();for(long id:ids)result.addAll(read(id,false));return result;}
            public EmployeeIdentity lock(Long id){return read(id,true).stream().findFirst().orElseThrow();}
            private List<EmployeeIdentity> read(long id,boolean lock){return jdbc.query("SELECT id,employee_number,name,status,employee_type,department_id,department FROM employee WHERE id=?"+(lock?" FOR UPDATE":""),(r,n)->new EmployeeIdentity(r.getLong(1),r.getString(2),r.getString(3),r.getString(4),r.getString(5),r.getObject(6,Long.class),r.getString(7)),id);}
        };}
        @Bean LoginSessionProperties sessionProperties(){var props=new LoginSessionProperties();props.setEnabled(true);return props;}
        @Bean RealtimeProperties realtimeProperties(){var props=new RealtimeProperties();props.setEnabled(true);props.setHeartbeatMillis(1000);props.setConnectionTtlMillis(30000);props.setMaxConnections(32);return props;}
        @Bean PasswordEncoder passwords(){return new BCryptPasswordEncoder();}
        @Bean AuthenticationManager authentication(UserDetailsServiceImpl users,PasswordEncoder password){var provider=new DaoAuthenticationProvider();provider.setUserDetailsService(users);provider.setPasswordEncoder(password);return new ProviderManager(provider);}
        @Bean SecurityFilterChain security(HttpSecurity security,JwtAuthenticationFilter jwt)throws Exception{
            security.csrf(csrf->csrf.disable()).requestCache(cache->cache.disable()).sessionManagement(session->session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                    .authorizeHttpRequests(authorize->authorize.dispatcherTypeMatchers(DispatcherType.ASYNC,DispatcherType.ERROR).permitAll().requestMatchers("/api/auth/login","/api/auth/logout","/api/auth/refresh").permitAll().anyRequest().authenticated())
                    .exceptionHandling(errors->errors.authenticationEntryPoint((request,response,failure)->response.setStatus(401)).accessDeniedHandler((request,response,failure)->response.setStatus(403)))
                    .addFilterBefore(jwt,UsernamePasswordAuthenticationFilter.class);return security.build();
        }
        @Bean ProbeParticipant probePolicy(JdbcTemplate jdbc,BusinessUserDirectory users){return new ProbeParticipant(jdbc,users);}
        @Bean ProbeService probe(JdbcTemplate jdbc){return new ProbeService(jdbc);}
        @Bean ProbeController probeController(ProbeService service){return new ProbeController(service);}
    }
    public record Command(long id,String name,Long expectedVersion,String requestId,boolean hold,boolean rollback){}
    @RestController static class ProbeController {
        final ProbeService service;ProbeController(ProbeService service){this.service=service;}
        @PostMapping("/__http_fixture/department") public Result<Map<String,Object>> write(@RequestBody Command command){return Result.success(service.write(command));}
    }
    static class ProbeService {
        final JdbcTemplate jdbc;ProbeService(JdbcTemplate jdbc){this.jdbc=jdbc;}
        @BusinessMutation(domain="ORGANIZATION",action="HTTP_FIXTURE_UPDATE",request="arg0.requestId",supervisorOnly=true)
        public Map<String,Object> write(Command command){
            jdbc.update("UPDATE organization_department SET name=? WHERE id=?",command.name(),command.id());
            if(command.hold()||command.rollback())TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization(){
                @Override public void beforeCommit(boolean readOnly){
                    if(command.hold()){var gate=CommitGate.current.get();if(gate==null)throw new IllegalStateException("missing commit gate");gate.entered.countDown();gate.waitForRelease();}
                    if(command.rollback())throw new IllegalStateException("fixture rollback after audit publication");
                }
            });
            return new LinkedHashMap<>(jdbc.queryForMap("SELECT id,name,version FROM organization_department WHERE id=?",command.id()));
        }
    }
    static class ProbeParticipant implements BusinessMutationParticipant,BusinessResourceAccess {
        final JdbcMutationSnapshots snapshots;final BusinessUserDirectory users;
        static final JdbcMutationSnapshots.Mapping ROW=new JdbcMutationSnapshots.Mapping("DEPARTMENT","organization_department","id","version",List.of("name"),Set.of(),Set.of());
        ProbeParticipant(JdbcTemplate jdbc,BusinessUserDirectory users){snapshots=new JdbcMutationSnapshots(jdbc);this.users=users;}
        public boolean supports(String domain,String action){return "ORGANIZATION".equals(domain)&&"HTTP_FIXTURE_UPDATE".equals(action);}
        public String resourceId(String domain,String action,Object[] args,Object result){return Long.toString(((Command)args[0]).id());}
        public Snapshot capture(AgentActor actor,String domain,String action,String id,boolean lock){if(!users.current(actor.userId(),actor.username()).supervisor())throw new SecurityException("supervisor required");return snapshots.capture(ROW,id,lock);}
        public Snapshot advanceVersion(Snapshot before,Snapshot after){return snapshots.advance(ROW,before,after);}
        public Object digestInput(String action,Object[] args){return args[0];}
        public boolean mayRead(AgentActor actor,String scope,String domain,String type,String id){try{return "ENTERPRISE".equals(scope)&&"ORGANIZATION".equals(domain)&&"DEPARTMENT".equals(type)&&users.current(actor.userId(),actor.username()).supervisor();}catch(RuntimeException denied){return false;}}
    }
    static class CommitGate {
        static final AtomicReference<CommitGate> current=new AtomicReference<>();
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        void waitForRelease(){try{if(!release.await(10,TimeUnit.SECONDS))throw new IllegalStateException("gate timeout");}catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new IllegalStateException(interrupted);}}
    }
    static class ResponseGate extends OncePerRequestFilter {
        static final AtomicReference<Delayed> current=new AtomicReference<>();
        record Delayed(String path,CommitGate gate){}
        @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
            var delayed=current.get();
            if(delayed==null||!delayed.path().equals(request.getServletPath())||!current.compareAndSet(delayed,null)){chain.doFilter(request,response);return;}
            var cached=new ContentCachingResponseWrapper(response);chain.doFilter(request,cached);delayed.gate().entered.countDown();delayed.gate().waitForRelease();cached.copyBodyToResponse();
        }
    }
    @BeforeAll void start()throws Exception{
        fixture=new OperationsMySqlFixture(false);jdbc=fixture.target();
        try{
            tomcatFiles=Files.createTempDirectory(Path.of("target").toAbsolutePath().normalize(),"http-fixture-tomcat-");
            jdbc.update("INSERT INTO organization_department(id,name) VALUES(20,'HTTP roster')");String password=new BCryptPasswordEncoder().encode(PASSWORD);
            for(int id=1;id<=4;id++){
                jdbc.update("INSERT INTO employee(id,employee_number,name,contact,department,employee_type,gender,hire_date,status,department_id) VALUES(?,?,?,'fixture','HTTP roster','DETECTION','UNKNOWN','2020-01-01','ACTIVE',20)",100+id,"HTTP-E"+id,"HTTP person "+id);
                jdbc.update("INSERT INTO users(id,username,password,role,employee_id,binding_version,binding_history_present) VALUES(?,?,?,?,?,1,TRUE)",id,username(id),password,id<=2?"SUPERVISOR":"INSPECTOR",100+id);
            }
            var properties=new LinkedHashMap<String,Object>();properties.put("collaboration.sessions.enabled","true");properties.put("collaboration.mutations.enabled","true");properties.put("collaboration.change-history.enabled","true");properties.put("collaboration.realtime.enabled","true");properties.put("operations.audit.enabled","true");properties.put("jwt.secret",SECRET);properties.put("jwt.expiration","3600");properties.put("jwt.refresh-expiration","86400");properties.put("app.security.cookie-secure","false");
            app=(ServletWebServerApplicationContext)new SpringApplicationBuilder(HttpApp.class).web(WebApplicationType.SERVLET).bannerMode(Banner.Mode.OFF).registerShutdownHook(false)
                    .initializers(context->context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("http-fixture-isolated",properties))).properties(properties).run();
            base=URI.create("http://127.0.0.1:"+app.getWebServer().getPort());
        }catch(Exception failure){if(app!=null)app.close();fixture.close();throw failure;}
    }
    @AfterAll void stop()throws Exception{try{if(app!=null)app.close();}finally{clients.shutdownNow();try{clients.awaitTermination(5,TimeUnit.SECONDS);}finally{if(fixture!=null)fixture.close();}}}
    @BeforeEach void freshDepartment(){department=ids.incrementAndGet();jdbc.update("INSERT INTO organization_department(id,name) VALUES(?,?)",department,"HTTP before "+department);}
    @AfterEach void closeStreams(){for(var stream:streams)stream.close();streams.clear();var commit=CommitGate.current.getAndSet(null);if(commit!=null)commit.release.countDown();ResponseGate.current.set(null);for(var gate:responseGates)gate.release.countDown();responseGates.clear();}
    static String username(int id){return id<=2?"http-boss-"+id:"http-inspector-"+id;}
    final class Browser {
        final CookieManager cookies=new CookieManager(null,CookiePolicy.ACCEPT_ALL);
        final HttpClient client=HttpClient.newBuilder().cookieHandler(cookies).executor(clients).version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(5)).build();
        String context;
        HttpRequest request(String method,String path,String body,boolean page){var builder=HttpRequest.newBuilder(base.resolve(path)).timeout(Duration.ofSeconds(15)).header("Accept","application/json");if(!"GET".equals(method))builder.header("Origin",base.toString());if(page&&context!=null)builder.header("X-Account-Context",context);return builder.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(body)).header("Content-Type","application/json").build();}
        HttpResponse<String> send(String method,String path,String body,boolean page)throws Exception{return client.send(request(method,path,body,page),HttpResponse.BodyHandlers.ofString());}
        HttpResponse<String> login(int id)throws Exception{var response=send("POST","/api/auth/login",json.writeValueAsString(Map.of("username",username(id),"password",PASSWORD)),false);assertThat(response.statusCode()).isEqualTo(200);context=data(response).path("accountContext").asText();assertThat(AuthCookieNames.validContext(context)).isTrue();return response;}
        HttpResponse<String> check()throws Exception{return send("GET","/api/auth/check",null,false);}
        String token(){return cookie(AuthCookieNames.access(context)).getValue();}
        HttpCookie cookie(String name){return cookies.getCookieStore().getCookies().stream().filter(c->name.equals(c.getName())).findFirst().orElseThrow();}
        CompletableFuture<HttpResponse<String>> authAsync(String operation){return client.sendAsync(request("POST","/api/auth/"+operation,"{}",true),HttpResponse.BodyHandlers.ofString());}
        HttpResponse<String> write(String request,String name,long expected,boolean hold,boolean rollback)throws Exception{return client.send(writeRequest(request,name,expected,hold,rollback,true),HttpResponse.BodyHandlers.ofString());}
        HttpRequest writeRequest(String request,String name,long expected,boolean hold,boolean rollback,boolean page)throws Exception{return request("POST","/__http_fixture/department",json.writeValueAsString(new Command(department,name,expected,request,hold,rollback)),page);}
    }
    Browser browser(int id)throws Exception{var browser=new Browser();browser.login(id);return browser;}
    JsonNode data(HttpResponse<String> response)throws Exception{return json.readTree(response.body()).path("data");}
    void identity(Browser browser,int id)throws Exception{var check=browser.check();assertThat(check.statusCode()).isEqualTo(200);var value=data(check);assertThat(value.path("userId").asText()).isEqualTo(String.valueOf(id));assertThat(value.path("role").asText()).isEqualTo(id<=2?"SUPERVISOR":"INSPECTOR");assertThat(value.path("identity").path("employeeId").asText()).isEqualTo(String.valueOf(100+id));assertThat(value.path("capabilities").path("realtime").asBoolean()).isTrue();}
    record Frame(String name,String id,JsonNode body){}
    final class Stream implements AutoCloseable {
        final InputStream body;final BlockingQueue<Frame> frames=new LinkedBlockingQueue<>(128);final List<Frame> seen=new CopyOnWriteArrayList<>();final CountDownLatch ended=new CountDownLatch(1);final Thread reader;
        Stream(Browser browser)throws Exception{
            var response=browser.client.send(HttpRequest.newBuilder(base.resolve("/api/realtime/changes")).header("Accept","text/event-stream").header("Origin",base.toString()).GET().build(),HttpResponse.BodyHandlers.ofInputStream());
            if(response.statusCode()!=200){response.body().close();assertThat(response.statusCode()).isEqualTo(200);}body=response.body();
            reader=new Thread(()->{try(var lines=new BufferedReader(new InputStreamReader(body,StandardCharsets.UTF_8))){String name="message",id=null,line;var data=new StringBuilder();while((line=lines.readLine())!=null){if(line.isEmpty()){if(!data.isEmpty()){var frame=new Frame(name,id,json.readTree(data.toString()));seen.add(frame);if(!frames.offer(frame))throw new IOException("fixture queue full");}name="message";id=null;data.setLength(0);}else if(line.startsWith("event:"))name=line.substring(6).trim();else if(line.startsWith("id:"))id=line.substring(3).trim();else if(line.startsWith("data:"))data.append(line.substring(5).trim());}}catch(IOException closed){/* EOF/closed TCP is an expected terminal path. */}finally{ended.countDown();}},"http-fixture-sse");reader.setDaemon(true);reader.start();
            take(frame->"resync-required".equals(frame.name())&&"CONNECTED".equals(frame.body().path("reason").asText()),5000);
        }
        Frame take(Predicate<Frame> match,long millis)throws Exception{long end=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(millis);while(System.nanoTime()<end){var frame=frames.poll(50,TimeUnit.MILLISECONDS);if(frame!=null&&match.test(frame))return frame;}throw new AssertionError("Expected authorized SSE frame");}
        Frame request(String request)throws Exception{return take(frame->"resource-changed".equals(frame.name())&&request.equals(frame.body().path("requestId").asText()),5000);}
        boolean received(String request){return seen.stream().anyMatch(frame->"resource-changed".equals(frame.name())&&request.equals(frame.body().path("requestId").asText()));}
        public void close(){try{body.close();}catch(IOException ignored){}reader.interrupt();}
    }
    Stream stream(Browser browser)throws Exception{var stream=new Stream(browser);streams.add(stream);return stream;}
    CommitGate delay(String path){var gate=new CommitGate();responseGates.add(gate);assertThat(ResponseGate.current.compareAndSet(null,new ResponseGate.Delayed(path,gate))).isTrue();return gate;}
    static void entered(CommitGate gate)throws Exception{assertThat(gate.entered.await(5,TimeUnit.SECONDS)).isTrue();}

    @Test @Order(1) void fourRealCookieClientsHaveIndependentPersonnelIdentityAndRejectStalePageWrites()throws Exception{
        var a=browser(1);var b=browser(2);var c=browser(3);var d=browser(4);identity(a,1);identity(b,2);identity(c,3);identity(d,4);
        assertThat(Set.of(a.context,b.context,c.context,d.context)).hasSize(4);
        assertThat(a.cookie(AuthCookieNames.SELECTOR).isHttpOnly()).isTrue();assertThat(a.cookie(AuthCookieNames.access(a.context)).getPath()).isEqualTo("/");assertThat(a.cookie(AuthCookieNames.refresh(a.context)).getPath()).isEqualTo("/api/auth");
        String old=a.context;a.context=b.context;var stale=a.write("stale-page","stale",0,false,false);a.context=old;assertThat(stale.statusCode()).isEqualTo(409);assertThat(json.readTree(stale.body()).path("code").asText()).isEqualTo("ACCOUNT_CONTEXT_CHANGED");
        var staleRead=a.client.send(HttpRequest.newBuilder(base.resolve("/api/auth/check")).header("X-Account-Context",b.context).GET().build(),HttpResponse.BodyHandlers.ofString());
        assertThat(staleRead.statusCode()).isEqualTo(409);assertThat(json.readTree(staleRead.body()).path("code").asText()).isEqualTo("ACCOUNT_CONTEXT_CHANGED");identity(a,1);
        assertThat(a.client.send(a.writeRequest("missing-page","missing",0,false,false,false),HttpResponse.BodyHandlers.ofString()).statusCode()).isEqualTo(409);
        assertThat(c.write("inspector-denied","denied",0,false,false).statusCode()).isEqualTo(403);assertThat(jdbc.queryForObject("SELECT version FROM organization_department WHERE id=?",Long.class,department)).isZero();
    }
    @Test @Order(2) void concurrentHttpVersionsAndIdempotentReceiptsAreAtomic()throws Exception{
        var a=browser(1);var b=browser(2);var first=a.client.sendAsync(a.writeRequest("concurrent-a","value-a",0,false,false,true),HttpResponse.BodyHandlers.ofString());var second=b.client.sendAsync(b.writeRequest("concurrent-b","value-b",0,false,false,true),HttpResponse.BodyHandlers.ofString());
        var ar=first.get(10,TimeUnit.SECONDS);var br=second.get(10,TimeUnit.SECONDS);assertThat(List.of(ar.statusCode(),br.statusCode())).containsExactlyInAnyOrder(200,409);
        boolean aw=ar.statusCode()==200;var winner=aw?a:b;var response=aw?ar:br;String request=aw?"concurrent-a":"concurrent-b",name=aw?"value-a":"value-b";
        var replay=winner.write(request,name,0,false,false);assertThat(replay.statusCode()).isEqualTo(200);assertThat(data(replay)).isEqualTo(data(response));assertThat(replay.headers().firstValue("X-Audit-ID")).isEqualTo(response.headers().firstValue("X-Audit-ID")).isPresent();
        assertThat(winner.write(request,"changed intent",0,false,false).statusCode()).isEqualTo(409);assertThat(jdbc.queryForObject("SELECT version FROM organization_department WHERE id=?",Long.class,department)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE kind='OPERATIONS' AND payload_version=2 AND resource_id=?",Integer.class,String.valueOf(department))).isEqualTo(1);
    }
    @Test @Order(3) void realSseFollowsCommitAndNeverPublishesARolledBackAudit()throws Exception{
        var writer=browser(1);var observer=browser(2);var stream=stream(observer);var gate=new CommitGate();CommitGate.current.set(gate);
        var pending=writer.client.sendAsync(writer.writeRequest("commit-held","committed",0,true,false,true),HttpResponse.BodyHandlers.ofString());entered(gate);
        assertThatThrownBy(()->stream.take(frame->"commit-held".equals(frame.body().path("requestId").asText()),200)).isInstanceOf(AssertionError.class);
        assertThat(stream.received("commit-held")).isFalse();assertThat(jdbc.queryForObject("SELECT version FROM organization_department WHERE id=?",Long.class,department)).isZero();
        gate.release.countDown();var saved=pending.get(10,TimeUnit.SECONDS);assertThat(saved.statusCode()).isEqualTo(200);var event=stream.request("commit-held");assertThat(event.body().path("auditId").asText()).isEqualTo(saved.headers().firstValue("X-Audit-ID").orElseThrow());assertThat(event.body().has("changes")).isFalse();
        assertThat(writer.write("rollback-audit","rolled-back",1,false,true).statusCode()).isEqualTo(500);
        assertThat(writer.write("after-rollback","final",1,false,false).statusCode()).isEqualTo(200);stream.request("after-rollback");assertThat(stream.received("rollback-audit")).isFalse();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM audit_event WHERE request_id='rollback-audit'",Integer.class)).isZero();assertThat(jdbc.queryForObject("SELECT version FROM organization_department WHERE id=?",Long.class,department)).isEqualTo(2);
    }
    @Test @Order(4) void singleSidLogoutClosesOnlyItsRealStreamAndOtherDevicesContinue()throws Exception{
        var a=browser(1);var device=browser(1);var peer=browser(2);var inspector=browser(3);var otherInspector=browser(4);var one=stream(a);var two=stream(device);var three=stream(peer);
        assertThat(a.send("POST","/api/auth/logout","{}",true).statusCode()).isEqualTo(200);assertThat(one.ended.await(5,TimeUnit.SECONDS)).isTrue();assertThat(a.check().statusCode()).isEqualTo(401);identity(device,1);identity(peer,2);identity(inspector,3);identity(otherInspector,4);
        assertThat(peer.write("surviving-device","continued",0,false,false).statusCode()).isEqualTo(200);two.request("surviving-device");three.request("surviving-device");assertThat(two.ended.getCount()).isEqualTo(1);
    }
    @Test @Order(5) void delayedOldRefreshCannotOverwriteAnotherAccountsLoginSelection()throws Exception{
        var browser=browser(1);String old=browser.context;var gate=delay("/api/auth/refresh");var refresh=browser.authAsync("refresh");entered(gate);assertThat(refresh.isDone()).isFalse();
        browser.login(2);identity(browser,2);gate.release.countDown();assertThat(refresh.get(10,TimeUnit.SECONDS).statusCode()).isEqualTo(200);identity(browser,2);
        assertThat(browser.cookie(AuthCookieNames.SELECTOR).getValue()).isEqualTo(browser.context).isNotEqualTo(old);assertThat(browser.write("after-late-refresh","account-b",0,false,false).statusCode()).isEqualTo(200);
    }
    @Test @Order(6) void delayedOldLogoutCannotClearAnotherAccountsLoginCookies()throws Exception{
        var browser=browser(1);var gate=delay("/api/auth/logout");var logout=browser.authAsync("logout");entered(gate);assertThat(logout.isDone()).isFalse();browser.login(2);identity(browser,2);
        gate.release.countDown();assertThat(logout.get(10,TimeUnit.SECONDS).statusCode()).isEqualTo(200);identity(browser,2);assertThat(browser.write("after-late-logout","account-b",0,false,false).statusCode()).isEqualTo(200);
    }
    @Test @Order(7) void lateRefreshAfterLogoutCannotRestoreRevokedAuthentication()throws Exception{
        var browser=browser(1);var other=browser(1);var stream=stream(browser);var gate=delay("/api/auth/refresh");var refresh=browser.authAsync("refresh");entered(gate);
        assertThat(browser.send("POST","/api/auth/logout","{}",true).statusCode()).isEqualTo(200);gate.release.countDown();assertThat(refresh.get(10,TimeUnit.SECONDS).statusCode()).isEqualTo(200);
        assertThat(browser.check().statusCode()).isEqualTo(401);assertThat(browser.send("POST","/api/auth/refresh","{}",true).statusCode()).isEqualTo(401);assertThat(stream.ended.await(5,TimeUnit.SECONDS)).isTrue();identity(other,1);
    }
    @Test @Order(8) void realAccessExpiryEndsSseWhileRefreshSessionRemainsUsable()throws Exception{
        var browser=browser(1);String token=browser.token();var jwt=app.getBean(JwtUtil.class);
        String shortAccess=io.jsonwebtoken.Jwts.builder().claim("uid",1L).claim("sid",jwt.getSessionId(token)).claim("type","access").setSubject(username(1)).setIssuedAt(new Date()).setExpiration(Date.from(Instant.now().plusSeconds(4))).signWith(io.jsonwebtoken.security.Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8)),io.jsonwebtoken.SignatureAlgorithm.HS256).compact();
        browser.cookie(AuthCookieNames.access(browser.context)).setValue(shortAccess);var stream=stream(browser);assertThat(stream.ended.await(8,TimeUnit.SECONDS)).isTrue();assertThat(browser.check().statusCode()).isEqualTo(401);
        assertThat(browser.send("POST","/api/auth/refresh","{}",true).statusCode()).isEqualTo(200);identity(browser,1);
    }
    @Test @Order(9) void accountAndPersonnelRevocationRejectUnexpiredCookiesAndCloseRealStreams()throws Exception{
        var boss=browser(1);var target=browser(2);var inspector=browser(3);var targetStream=stream(target);var inspectorStream=stream(inspector);assertThat(app.getBean(JwtUtil.class).getExpiresAt(target.token())).isAfter(Instant.now());
        var current=boss.send("GET","/api/accounts/2/access",null,false);String version=data(current).path("accountVersion").asText();
        var command=json.writeValueAsString(Map.of("enabled",false,"role","SUPERVISOR","expectedVersion",Long.parseLong(version),"requestId","disable-http-boss"));
        assertThat(boss.send("POST","/api/accounts/2/access",command,true).statusCode()).isEqualTo(200);assertThat(target.check().statusCode()).isEqualTo(401);assertThat(targetStream.ended.await(5,TimeUnit.SECONDS)).isTrue();
        new TransactionTemplate(app.getBean(PlatformTransactionManager.class)).executeWithoutResult(status->{jdbc.update("UPDATE employee SET employee_type='COLLECTION' WHERE id=103");app.publishEvent(new EmployeeLoginEligibilityChanged(103));});
        assertThat(inspector.check().statusCode()).isEqualTo(401);assertThat(inspectorStream.ended.await(5,TimeUnit.SECONDS)).isTrue();identity(boss,1);
    }
}
