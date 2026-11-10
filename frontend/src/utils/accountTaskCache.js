// Private upload state is owned by a verified account lifetime, never by the latest cookie.
export function createAccountTaskCache({ session, storage }) {
  const prefix = context => context ? 'doorhandle:' + encodeURIComponent(context) + ':' : null
  const owned = stamp => !!stamp?.accountContext && session.current(stamp) && session.state.authenticated
  const fileKey = (context, taskId) => prefix(context) + 'task_files_' + encodeURIComponent(taskId)
  return {
    writeTasks(value, stamp) { if (!owned(stamp)) return false; try { storage()?.setItem(prefix(stamp.accountContext)+'taskList',JSON.stringify(value));return true } catch { return false } },
    writeFile(taskId, value, stamp) { if (!owned(stamp)) return false; try { storage()?.setItem(fileKey(stamp.accountContext,taskId),JSON.stringify(value));return true } catch { return false } },
    readTasks() { try { const key=prefix(session.state.accountContext);return key&&session.state.authenticated?JSON.parse(storage()?.getItem(key+'taskList')||'[]'):[] } catch { return [] } },
    readFile(taskId) { try { return session.state.accountContext&&session.state.authenticated?JSON.parse(storage()?.getItem(fileKey(session.state.accountContext,taskId))||'null'):null } catch { return null } },
    removeFile(taskId,stamp) { if(!owned(stamp))return false;try{storage()?.removeItem(fileKey(stamp.accountContext,taskId));return true}catch{return false} },
    clear(context) {
      const namespace=prefix(context);if(!namespace)return
      try { const target=storage(), keys=[];for(let i=0;i<(target?.length||0);i++){const key=target.key(i);if(key===namespace+'taskList'||key?.startsWith(namespace+'task_files_'))keys.push(key)}for(const key of keys)target.removeItem(key) } catch { /* Storage access may be disabled. Memory still resets. */ }
    },
  }
}
