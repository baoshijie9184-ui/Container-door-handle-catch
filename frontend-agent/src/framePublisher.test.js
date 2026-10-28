import {test} from 'node:test';
import assert from 'node:assert/strict';
import {framePublisher} from './framePublisher.js';
test('coalesces stream updates without losing the latest state or terminal flush',()=>{
  const callbacks=[],values=[],cancelled=[];const publisher=framePublisher(value=>values.push(value),fn=>{callbacks.push(fn);return callbacks.length;},id=>cancelled.push(id));
  publisher.push('a');publisher.push('ab');publisher.push('abc');assert.equal(callbacks.length,1);callbacks[0]();assert.deepEqual(values,['abc']);
  publisher.push('finished');publisher.finish();assert.deepEqual(values,['abc','finished']);assert.deepEqual(cancelled,[2]);publisher.close();publisher.push('late');assert.equal(callbacks.length,2);
});
