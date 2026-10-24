package com.ruanzhu.doorhandle.module.system.api;

import com.ruanzhu.doorhandle.contracts.security.BusinessUserDirectory;
import com.ruanzhu.doorhandle.module.system.mapper.UserMapper;
import org.springframework.stereotype.Service;

@Service
public class BusinessUserDirectoryImpl implements BusinessUserDirectory,com.ruanzhu.doorhandle.contracts.security.BusinessAccountLookupApi {
    private final UserMapper users;
    public BusinessUserDirectoryImpl(UserMapper users) { this.users = users; }
    @Override public Identity authenticated() {
        var authentication=org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication();
        if(authentication==null || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof com.ruanzhu.doorhandle.module.system.security.TenantPrincipal principal) || principal.userId()==null)
            throw new SecurityException("业务变更缺少受信账号");
        return current(principal.userId(),principal.username());
    }
    public Long findExactUserId(String username) {
        if(username==null||username.isBlank())return null;
        var matches=users.selectList(publicFields().eq("username",username))
                .stream().filter(user->username.equals(user.getUsername())).toList();
        return matches.size()==1?matches.get(0).getId():null;
    }
    public String username(long userId){var user=users.selectOne(publicFields().eq("id",userId));return user==null?null:user.getUsername();}
    private com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User> publicFields() {
        return new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<com.ruanzhu.doorhandle.module.system.entity.User>()
                .select("id", "username", "role", "created_at", "updated_at");
    }
    @Override public Account describe(long userId) {
        if(userId<1)return null;
        var user=users.selectOne(publicFields().eq("id",userId));
        if(user==null)return null;
        try{return BusinessAccountSnapshot.describe(user);}catch(IllegalArgumentException unavailable){return null;}
    }
    @Override public java.util.List<Account> search(String keyword,int limit) {
        if(keyword==null||keyword.length()>64||limit<1||limit>30)throw new IllegalArgumentException("账号检索参数无效");
        var query=publicFields().in("role",java.util.List.of("ADMIN","SUPERVISOR","INSPECTOR","OPERATOR"));
        Long id=null;
        if(keyword.matches("[1-9][0-9]{0,18}")){try{id=Long.parseLong(keyword);}catch(NumberFormatException ignored){}}
        final Long selectedId=id;
        if(!keyword.isBlank())query.and(part->{part.like("username",keyword);if(selectedId!=null)part.or().eq("id",selectedId);});
        return users.selectList(query.orderByAsc("id").last("LIMIT "+limit)).stream()
                .map(BusinessAccountSnapshot::describe).toList();
    }
    @Override
    @org.springframework.transaction.annotation.Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY)
    public Account lock(Account expected) {
        if(expected==null||expected.userId()<1||expected.revision()==null)throw new IllegalArgumentException("缺少已选择的目标账号快照");
        var user=users.selectOne(publicFields().eq("id",expected.userId()).last("FOR SHARE"));
        if(user==null||!expected.equals(BusinessAccountSnapshot.describe(user)))throw new IllegalArgumentException("目标账号资料已变化，请重新选择并确认");
        return expected;
    }
    @Override
    @org.springframework.transaction.annotation.Transactional(propagation=org.springframework.transaction.annotation.Propagation.MANDATORY)
    public Identity lockCurrent(long userId,String username) {
        return identity(users.selectOne(publicFields().eq("id",userId).last("FOR SHARE")),userId,username);
    }
    public Identity current(long userId, String username) {
        var user = users.selectOne(publicFields().eq("id",userId));
        return identity(user,userId,username);
    }
    private Identity identity(com.ruanzhu.doorhandle.module.system.entity.User user,long userId,String username) {
        if (user == null || userId <= 0 || username == null || !username.equals(user.getUsername()))
            throw new SecurityException("当前账号身份已失效");
        String role=user.getRole()==null?"":user.getRole().toUpperCase(java.util.Locale.ROOT);
        if(!java.util.Set.of("SUPERVISOR","ADMIN","INSPECTOR","OPERATOR").contains(role))
            throw new SecurityException("当前账号没有业务助手权限");
        return new Identity(userId, username, "SUPERVISOR".equalsIgnoreCase(user.getRole()) || "ADMIN".equalsIgnoreCase(user.getRole()));
    }
}
