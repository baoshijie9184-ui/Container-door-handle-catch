package com.ruanzhu.doorhandle.contracts.security;

/** 业务写操作重新核对账号；身份只能由服务端认证上下文传入。 */
public interface BusinessUserDirectory {
    record Identity(long userId, String username, boolean supervisor) {}
    Identity current(long userId, String username);
}
