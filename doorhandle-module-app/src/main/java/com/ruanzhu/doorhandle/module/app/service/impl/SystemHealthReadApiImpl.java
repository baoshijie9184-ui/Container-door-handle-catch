package com.ruanzhu.doorhandle.module.app.service.impl;

import com.ruanzhu.doorhandle.contracts.agent.*;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.actuate.health.HealthEndpoint;
import org.springframework.stereotype.Service;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;

/** 复用本模块 Actuator；只执行固定探针，有界线程/队列与全局预算，拒绝任意地址或运维命令。 */
@Service
public class SystemHealthReadApiImpl implements SystemHealthReadApi, AutoCloseable {
    private static final List<String> PROBES = List.of("livenessState", "readinessState", "diskSpace", "db", "redis");
    private static final List<String> NOT_MONITORED = List.of("kafka", "detectionWorker", "mem0", "oss", "higress", "mcpGateway", "chroma", "llmProviders");
    private static final Set<String> STATUSES = Set.of("UP", "DOWN", "OUT_OF_SERVICE", "UNKNOWN");
    private final ObjectProvider<HealthEndpoint> endpoints;
    private final ThreadPoolExecutor executor;
    private final Duration budget, cacheTtl;
    private Snapshot cached;
    private long cachedAtNanos;

    @Autowired
    public SystemHealthReadApiImpl(ObjectProvider<HealthEndpoint> endpoints) {
        this(endpoints, Duration.ofSeconds(2), Duration.ofSeconds(30));
    }
    SystemHealthReadApiImpl(ObjectProvider<HealthEndpoint> endpoints, Duration budget, Duration cacheTtl) {
        this.endpoints = endpoints; this.budget = budget; this.cacheTtl = cacheTtl;
        this.executor = new ThreadPoolExecutor(3, 3, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(3), runnable -> {
            var thread = new Thread(runnable, "agent-health-probe"); thread.setDaemon(true); return thread;
        }, new ThreadPoolExecutor.AbortPolicy());
    }
    @Override
    public synchronized Snapshot snapshot(AgentActor actor) {
        actor.requireSupervisor(); // 缓存也不能被员工读取。
        if (cached != null && System.nanoTime() - cachedAtNanos < cacheTtl.toNanos()) return cached;
        long deadline = System.nanoTime() + budget.toNanos();
        var futures = new LinkedHashMap<String,Future<Component>>();
        var components = new ArrayList<Component>();
        for (String id : PROBES) {
            try { futures.put(id, executor.submit(() -> probe(id))); }
            catch (RejectedExecutionException error) { futures.put(id, null); }
        }
        try {
            for (var entry : futures.entrySet()) {
                Future<Component> future = entry.getValue();
                if (future == null) { components.add(unknown(entry.getKey(), "BUSY")); continue; }
                try { components.add(future.get(Math.max(0,deadline-System.nanoTime()), TimeUnit.NANOSECONDS)); }
                catch (TimeoutException error) { future.cancel(true); components.add(unknown(entry.getKey(), "TIMED_OUT")); }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); components.add(unknown(entry.getKey(), "INTERRUPTED")); }
                catch (ExecutionException | CancellationException error) { components.add(unknown(entry.getKey(), "CHECK_FAILED")); }
            }
        } finally {
            futures.values().stream().filter(Objects::nonNull).filter(future -> !future.isDone()).forEach(future -> future.cancel(true));
            executor.purge(); // 不能让取消但未执行的任务长期占据队列。
        }
        String status = components.stream().anyMatch(c -> c.status().equals("DOWN")) ? "DOWN"
                : components.stream().anyMatch(c -> c.status().equals("OUT_OF_SERVICE")) ? "OUT_OF_SERVICE"
                : components.stream().anyMatch(c -> !c.status().equals("UP")) ? "UNKNOWN" : "UP";
        Instant now = Instant.now();
        cached = new Snapshot(status,components,NOT_MONITORED,now,now.plus(cacheTtl)); cachedAtNanos = System.nanoTime();
        return cached;
    }
    private Component probe(String id) {
        try {
            var endpoint = endpoints.getIfAvailable();
            if (endpoint == null) return unknown(id,"NOT_REGISTERED");
            var health = endpoint.healthForPath(id);
            if (health == null) return unknown(id,"NOT_REGISTERED");
            String status = health.getStatus().getCode();
            return new Component(id,STATUSES.contains(status) ? status : "UNKNOWN","ACTUATOR");
        } catch (RuntimeException error) { return unknown(id,"CHECK_FAILED"); }
    }
    private Component unknown(String id,String reason) { return new Component(id,"UNKNOWN",reason); }
    @Override @PreDestroy public void close() { executor.shutdownNow(); }
}
