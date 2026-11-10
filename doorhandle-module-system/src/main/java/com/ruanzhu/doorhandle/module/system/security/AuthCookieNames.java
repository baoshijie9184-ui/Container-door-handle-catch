package com.ruanzhu.doorhandle.module.system.security;

import com.ruanzhu.doorhandle.module.system.controller.AuthController;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.authentication.CredentialsExpiredException;

/** The selector is written only by login; late refresh/logout responses address their own context. */
public final class AuthCookieNames {
    public static final String SELECTOR="DOOR_HANDLE_CONTEXT";
    private AuthCookieNames(){}
    public static boolean validContext(String context){return context!=null&&context.matches("[A-Za-z0-9_-]{43}");}
    public static String access(String context){require(context);return AuthController.AUTH_COOKIE_NAME+"_"+context;}
    public static String refresh(String context){require(context);return AuthController.REFRESH_COOKIE_NAME+"_"+context;}
    public static boolean scoped(String name){return name!=null&&(name.matches("DOOR_HANDLE_TOKEN_[A-Za-z0-9_-]{43}")||name.matches("DOOR_HANDLE_REFRESH_TOKEN_[A-Za-z0-9_-]{43}"));}
    public static boolean authentication(String name){return SELECTOR.equals(name)||AuthController.AUTH_COOKIE_NAME.equals(name)||AuthController.REFRESH_COOKIE_NAME.equals(name)||scoped(name);}
    public static String selected(HttpServletRequest request){
        String selected=null;boolean present=false;
        if(request.getCookies()!=null)for(var cookie:request.getCookies())if(SELECTOR.equals(cookie.getName())){
            if(present||!validContext(cookie.getValue()))throw new CredentialsExpiredException("登录上下文选择无效，请重新登录");
            present=true;selected=cookie.getValue();
        }
        return selected;
    }
    public static String value(HttpServletRequest request,String name){
        String value=null;boolean present=false;
        if(request.getCookies()!=null)for(var cookie:request.getCookies())if(name.equals(cookie.getName())){
            if(present)throw new CredentialsExpiredException("登录凭据重复，请重新登录");present=true;value=cookie.getValue();
        }
        return value==null||value.isBlank()?null:value;
    }
    private static void require(String context){if(!validContext(context))throw new IllegalArgumentException("登录上下文格式无效");}
}
