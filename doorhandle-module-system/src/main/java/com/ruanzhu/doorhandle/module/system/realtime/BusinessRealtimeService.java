package com.ruanzhu.doorhandle.module.system.realtime;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceAccess;
import com.ruanzhu.doorhandle.contracts.collaboration.BusinessResourceChanged;
import com.ruanzhu.doorhandle.contracts.security.AccountAccessChanged;
import com.ruanzhu.doorhandle.contracts.security.LoginSessionAccess;
import com.ruanzhu.doorhandle.contracts.security.LoginSessionRevoked;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** Notifications are hints. Authoritative data/history are re-read over authenticated HTTP. */
@Service
@ConditionalOnProperty(prefix = "collaboration.realtime", name = "enabled", havingValue = "true")
public class BusinessRealtimeService {
    interface Transport {
        void send(String name, String id, Map<String, Object> body) throws Exception;
        void complete();
    }
    private record Frame(String name, BusinessResourceChanged change, String reason) { }
    private final LoginSessionAccess sessions;
    private final List<BusinessResourceAccess> access;
    private final RealtimeProperties properties;
    private final Map<String, Connection> connections = new ConcurrentHashMap<>();
    // Admission slots include closing writers until their blocking socket call actually returns.
    private final Map<Long, Integer> userSlots = new HashMap<>();
    private int slots;
    private final AtomicBoolean stopped = new AtomicBoolean();
    private final AtomicBoolean resyncAll = new AtomicBoolean();
    private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(daemon("business-realtime-clock"));
    private final ThreadPoolExecutor events = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(256), daemon("business-realtime-events"), new ThreadPoolExecutor.AbortPolicy());

    public BusinessRealtimeService(LoginSessionAccess sessions, List<BusinessResourceAccess> access, RealtimeProperties properties) {
        this.sessions = sessions; this.access = List.copyOf(access); this.properties = properties;
    }
    @PostConstruct void start() { timer.scheduleWithFixedDelay(this::tick, 1, 1, TimeUnit.SECONDS); }

    public SseEmitter open(long userId, String username, String digest, String context, Instant accessExpiresAt) {
        var session = sessions.requireActive(userId, username, digest);
        if (context == null || !context.equals(session.accountContext()) || accessExpiresAt == null
                || !accessExpiresAt.isAfter(Instant.now())) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        var expiry = min(accessExpiresAt, min(session.expiresAt(), Instant.now().plusMillis(properties.getConnectionTtlMillis())));
        var emitter = new SseEmitter(Math.max(1, expiry.toEpochMilli() - System.currentTimeMillis()));
        var channel = new Transport() {
            public void send(String name, String id, Map<String, Object> body) throws Exception {
                var event = SseEmitter.event().name(name).data(body, org.springframework.http.MediaType.APPLICATION_JSON);
                if (id != null) event.id(id);
                emitter.send(event);
            }
            public void complete() { emitter.complete(); }
        };
        var connection = register(session, expiry, channel);
        emitter.onCompletion(connection::close);
        emitter.onTimeout(connection::close);
        emitter.onError(error -> connection.close());
        connection.begin();
        return emitter;
    }

    Connection register(LoginSessionAccess.Session session, Instant accessExpiry, Transport channel) {
        if (session.sessionDigest() == null || session.sessionDigest().isBlank() || session.accountContext() == null
                || !accessExpiry.isAfter(Instant.now())) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        synchronized (userSlots) {
            if (stopped.get()) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE);
            int count = userSlots.getOrDefault(session.userId(), 0);
            if (slots >= properties.getMaxConnections() || count >= properties.getMaxConnectionsPerUser())
                throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "实时连接已达上限，请稍后重试");
            var connection = new Connection(session, min(accessExpiry, session.expiresAt()), channel);
            slots++; userSlots.put(session.userId(), count + 1);
            connections.put(connection.id, connection);
            return connection;
        }
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void committed(BusinessResourceChanged event) {
        // Never perform authorization/network I/O on the committed business transaction's thread.
        if (stopped.get()) return;
        try { events.execute(() -> publish(event)); }
        catch (RejectedExecutionException busy) { resyncAll.set(true); }
    }
    void publish(BusinessResourceChanged event) {
        if (event == null || !safe(event.eventId(), 128)) return;
        for (var connection : connections.values()) {
            // A former assignee also needs a non-identifying invalidation to clear a stale detail.
            if ("ENTERPRISE".equals(event.scope())) connection.offer(new Frame("resync-required", null, "BUSINESS_CHANGED"));
            if ("PRIVATE".equals(event.scope()) && !Objects.equals(connection.session.userId(), event.actorUserId())) continue;
            if (!Set.of("PRIVATE", "ENTERPRISE").contains(event.scope())) continue;
            connection.offer(new Frame("resource-changed", event, null));
        }
    }
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void revoked(LoginSessionRevoked event) {
        connections.values().stream().filter(c -> c.session.userId() == event.userId()
                && Objects.equals(c.session.sessionDigest(), event.sessionDigest())).forEach(Connection::close);
    }
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void accountChanged(AccountAccessChanged event) {
        connections.values().stream().filter(c -> c.session.userId() == event.userId()).forEach(Connection::close);
        resyncAll.set(true);
    }
    private void tick() {
        try {
            boolean resync = resyncAll.getAndSet(false);
            long now = System.currentTimeMillis(), nano = System.nanoTime();
            for (var c : connections.values()) {
                long sendStart = c.sendingSince.get();
                if (now >= c.expiry.toEpochMilli() || (sendStart > 0 && nano - sendStart > TimeUnit.MILLISECONDS.toNanos(properties.getSendTimeoutMillis()))) {
                    c.close(); continue;
                }
                if (resync) c.offer(new Frame("resync-required", null, "NOTIFICATIONS_DROPPED"));
                if (now - c.lastHeartbeat >= properties.getHeartbeatMillis()) {
                    c.lastHeartbeat = now; c.offer(new Frame("heartbeat", null, null));
                }
            }
        } catch (RuntimeException ignored) { resyncAll.set(true); }
    }
    @PreDestroy public void stop() {
        if (!stopped.compareAndSet(false, true)) return;
        events.shutdownNow(); timer.shutdownNow();
        connections.values().forEach(Connection::close);
    }

    final class Connection implements Runnable {
        private final String id = UUID.randomUUID().toString();
        private final LoginSessionAccess.Session session;
        private final Instant expiry;
        private final Transport channel;
        private final BlockingQueue<Frame> queue = new ArrayBlockingQueue<>(properties.getQueueCapacity());
        private final AtomicBoolean closed = new AtomicBoolean();
        private final AtomicBoolean begun = new AtomicBoolean();
        private final AtomicLong sendingSince = new AtomicLong();
        private final Thread writer;
        private volatile long lastHeartbeat = System.currentTimeMillis();
        Connection(LoginSessionAccess.Session session, Instant expiry, Transport channel) {
            this.session = session; this.expiry = expiry; this.channel = channel;
            writer = daemon("business-realtime-client").newThread(this);
        }
        void begin() { if (begun.compareAndSet(false, true)) { queue.offer(new Frame("resync-required", null, "CONNECTED")); writer.start(); } }
        void offer(Frame frame) {
            if (!closed.get() && !queue.offer(frame)) close(); // Reconnect always requests an authoritative resync.
        }
        void close() {
            if (!closed.compareAndSet(false, true)) return;
            connections.remove(id, this); queue.clear(); writer.interrupt();
            // Completion is performed only by this client's writer; never block the shared clock/listener.
        }
        public void run() {
            try {
                int sent = 0;
                while (!closed.get() && sent < properties.getEventBudget()) {
                    Frame frame = queue.poll(1, TimeUnit.SECONDS);
                    if (frame == null) continue;
                    if (!Instant.now().isBefore(expiry)) break;
                    var fresh = sessions.requireActive(session.userId(), session.username(), session.sessionDigest());
                    if (!Objects.equals(fresh.accountContext(), session.accountContext()) || !Instant.now().isBefore(fresh.expiresAt())) break;
                    var body = new LinkedHashMap<String, Object>();
                    body.put("schemaVersion", 1); body.put("occurredAt", Instant.now().toString()); body.put("accountContext", session.accountContext());
                    String eventId = null;
                    if (frame.change != null) {
                        var e = frame.change;
                        var actor = new AgentActor(fresh.userId(), fresh.username(), AgentActor.Role.valueOf(fresh.role()));
                        boolean allowed = false;
                        for (var policy : access) if (policy.mayRead(actor, e.scope(), e.domain(), e.resourceType(), e.resourceId())) { allowed = true; break; }
                        if (!allowed) continue;
                        body.put("eventId", e.eventId()); body.put("auditId", e.auditId()); body.put("domain", e.domain());
                        body.put("resourceType", e.resourceType()); body.put("resourceId", e.resourceId());
                        body.put("resourceVersion", e.resourceVersion()); body.put("action", e.action()); body.put("requestId", e.requestId());
                        body.put("occurredAt", e.occurredAt().toString()); eventId = e.eventId();
                    } else if (frame.reason != null) body.put("reason", frame.reason);
                    if (closed.get() || !Instant.now().isBefore(expiry)) break;
                    sendingSince.set(System.nanoTime());
                    try { channel.send(frame.name, eventId, body); } finally { sendingSince.set(0); }
                    sent++;
                }
            } catch (Exception unavailable) {
                // Client failure/session revocation only closes this connection. No business payload logging.
            } finally {
                close();
                try { channel.complete(); } catch (RuntimeException ignored) { }
                synchronized (userSlots) {
                    slots--; userSlots.compute(session.userId(), (uid, n) -> n == null || n <= 1 ? null : n - 1);
                }
            }
        }
    }
    int activeSlots() { synchronized (userSlots) { return slots; } }
    private static Instant min(Instant a, Instant b) { return a.isBefore(b) ? a : b; }
    private static boolean safe(String value, int max) { return value != null && !value.isBlank() && value.length() <= max && value.chars().noneMatch(c -> c < 32 || c == 127); }
    private static ThreadFactory daemon(String name) { return runnable -> { var thread = new Thread(runnable, name); thread.setDaemon(true); return thread; }; }
}
