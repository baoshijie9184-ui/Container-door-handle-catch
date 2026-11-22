package com.ruanzhu.doorhandle.module.ai.agent;

import com.ruanzhu.doorhandle.contracts.agent.AgentActor;
import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.ai.journal.AgentJournalMiddleware;
import com.ruanzhu.doorhandle.module.ai.mcp.FetchMcpRuntime;
import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.middleware.MiddlewareBase;
import java.net.URI;
import java.util.HashSet;
import java.util.Set;
import java.util.function.Function;
import java.util.regex.Pattern;
import org.springframework.security.access.AccessDeniedException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

/** Rechecks the authenticated account at execution, independently of journal settings. */
final class AgentToolAccess implements MiddlewareBase {
    private static final Pattern WEB_URL = Pattern.compile("(?i)https?://[^\\s<>\\[\\]()\"'，。；、]+");
    private final AgentActor actor;
    private final BusinessUserDirectory users;
    private final Set<String> allowedTools;
    private final Set<URI> fetchTargets;
    private final AgentJournalMiddleware audit;

    AgentToolAccess(AgentActor actor, BusinessUserDirectory users, Set<String> allowedTools,
                    String userRequest, AgentJournalMiddleware audit) {
        this.actor = actor;
        this.users = users;
        this.allowedTools = Set.copyOf(allowedTools);
        this.fetchTargets = allowedTools.contains(FetchMcpRuntime.TOOL) ? requestedUrls(userRequest) : Set.of();
        this.audit = audit;
    }

    @Override
    public int order() {
        return 20;
    }

    @Override
    public Flux<AgentEvent> onActing(Agent agent, RuntimeContext context, ActingInput input,
                                   Function<ActingInput, Flux<AgentEvent>> next) {
        if (input.toolCalls().isEmpty()) return Flux.defer(() -> next.apply(input));
        return Mono.fromRunnable(() -> authorize(input))
                .subscribeOn(Schedulers.boundedElastic())
                .doOnError(AccessDeniedException.class, denied -> {
                    if (audit != null) audit.recordToolAccessDenied(agent.getName());
                })
                .thenMany(Flux.defer(() -> next.apply(input)));
    }

    private void authorize(ActingInput input) {
        if (input.toolCalls().stream().anyMatch(call -> call.getName() == null || !allowedTools.contains(call.getName()))) {
            throw new AccessDeniedException("当前账号无权调用此工具");
        }
        for (var call : input.toolCalls()) {
            if (FetchMcpRuntime.TOOL.equals(call.getName())) {
                Object url = call.getInput() == null ? null : call.getInput().get("url");
                URI target = url instanceof String value ? webUri(value) : null;
                if (target == null || !fetchTargets.contains(target)) {
                    throw new AccessDeniedException("Fetch 只能读取用户在本轮明确提供的网址");
                }
            }
        }
        if (users == null) return;
        BusinessUserDirectory.Identity current;
        try {
            current = users.current(actor.userId(), actor.username());
        } catch (SecurityException denied) {
            throw new AccessDeniedException("当前账号权限已失效，请重新登录", denied);
        }
        if (current == null || current.userId() != actor.userId() || !actor.username().equals(current.username())
                || current.supervisor() != actor.supervisor()) {
            throw new AccessDeniedException("当前账号权限已变化，请重新发起对话");
        }
    }

    private static Set<URI> requestedUrls(String request) {
        if (request == null || request.isBlank()) return Set.of();
        var urls = new HashSet<URI>();
        var matcher = WEB_URL.matcher(request);
        while (matcher.find()) {
            URI uri = webUri(matcher.group());
            if (uri != null) urls.add(uri);
        }
        return Set.copyOf(urls);
    }

    private static URI webUri(String raw) {
        try {
            URI uri = URI.create(raw);
            if (uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawFragment() != null
                    || !("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme()))) return null;
            if (uri.getRawPath().isEmpty()) {
                return URI.create(uri.getScheme() + "://" + uri.getRawAuthority() + "/"
                        + (uri.getRawQuery() == null ? "" : "?" + uri.getRawQuery()));
            }
            return uri;
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }
}
