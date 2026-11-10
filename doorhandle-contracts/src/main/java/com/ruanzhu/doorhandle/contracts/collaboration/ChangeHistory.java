package com.ruanzhu.doorhandle.contracts.collaboration;

import java.time.Instant;
import java.util.List;

/** Public history wire types. Identifiers and revisions remain decimal strings across JavaScript clients. */
public final class ChangeHistory {
    private ChangeHistory() { }
    public record Actor(String userId, String username, String displayName, String role) { }
    /** Null is SQL NULL; absence is represented by operation ADD/REMOVE, never by an empty string. */
    public record Change(String field, String label, String operation, Object before, Object after,
                         String valueType, boolean redacted) {
        /** One numeric representation survives JDBC and JSON without collapsing numbers into strings. */
        public Change { before=canonical(before); after=canonical(after); }
        private static Object canonical(Object value) {
            return value instanceof Number number?new java.math.BigDecimal(number.toString()).stripTrailingZeros():value;
        }
    }
    public record Item(String id, String eventId, Actor actor, String domain, String resourceType,
            String resourceId, String action, String result, String beforeVersion, String afterVersion,
            String requestId, Instant occurredAt, String scope, boolean diffAvailable) { }
    public record Page(List<Item> items, String nextCursor) {
        public Page { items = List.copyOf(items); }
    }
    public record Detail(String id, String eventId, Actor actor, String domain, String resourceType,
            String resourceId, String action, String result, String beforeVersion, String afterVersion,
            String requestId, Instant occurredAt, String scope, boolean diffAvailable, List<Change> changes) {
        public Detail { changes = List.copyOf(changes); }
    }
}
