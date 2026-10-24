package com.ruanzhu.doorhandle.contracts.security;

/** Exact stable identity lookup. A display name is never an account identifier. */
public interface BusinessAccountLookupApi {
    /** Public-safe selection material. Revision is a snapshot hash, not an ordered account version. */
    record Account(long userId, String username, String role, String revision) {}
    Long findExactUserId(String username);
    String username(long userId);
    default Account describe(long userId) { throw new SecurityException("账号快照未接入"); }
    default java.util.List<Account> search(String keyword, int limit) { throw new SecurityException("账号选择未接入"); }
    /** Must hold the selected account against changes in the caller's business transaction. */
    default Account lock(Account expected) { throw new SecurityException("账号确认锁未接入"); }
}
