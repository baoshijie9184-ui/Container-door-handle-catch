// Keep Markdown rendering at most once per animation frame while retaining every delta.
export function framePublisher(publish,schedule=callback=>requestAnimationFrame(callback),cancel=id=>cancelAnimationFrame(id)) {
  let pending=null,latest,closed=false;
  const flush=()=>{pending=null;if(!closed&&latest!==undefined){const value=latest;latest=undefined;publish(value);}};
  return {
    push(value){if(closed)return;latest=value;if(pending===null)pending=schedule(flush);},
    finish(){if(pending!==null)cancel(pending);pending=null;flush();},
    close(){closed=true;if(pending!==null)cancel(pending);pending=null;latest=undefined;},
  };
}
