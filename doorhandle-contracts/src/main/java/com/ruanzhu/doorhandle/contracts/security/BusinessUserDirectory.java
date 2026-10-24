package com.ruanzhu.doorhandle.contracts.security;

/** 业务写操作重新核对账号；身份只能由服务端认证上下文传入。 */
public interface BusinessUserDirectory {
    record Identity(long userId, String username, boolean supervisor) {}
    Identity current(long userId, String username);
    /** Refresh and retain the actual actor role for a sensitive business transaction. */
    default Identity lockCurrent(long userId, String username) { throw new SecurityException("业务身份确认锁未接入"); }
    /** Resolve only a trusted server principal with its stable user ID, never a name supplied by a client. */
    default Identity authenticated() { throw new SecurityException("当前业务身份未接入"); }
}
