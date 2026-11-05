"use strict";
const $=id=>document.getElementById(id);
let snapshot=null;
function element(tag,text){const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;}
function error(message){$("error").hidden=!message;$("error").textContent=message||"";}
function inspect(title,explanation,records){$("evidence-title").textContent=title;$("explanation").textContent=explanation;$("record").textContent=JSON.stringify(records,null,2);$("evidence").showModal();}
function render(data){
 snapshot=data;error(data.error);if(!data.control)return;
 $("run").textContent=`Run ${data.control.run_id} | phase: ${data.phase} | ${data.complete?"complete":data.control.mode} | updated ${new Date(data.generated_at*1000).toLocaleTimeString()}`;
 $("health").replaceChildren();
 for(const [name,value] of Object.entries(data.health)){const row=element("tr");[name,value.state,value.bad_records,value.kind].forEach(v=>row.append(element("td",String(v))));$("health").append(row);}
 $("counts").textContent=`Retained in this run: ${data.counts.gpu_samples} GPU samples, ${data.counts.flows} connections, ${data.counts.canary} decoy events.`;
 $("findings").replaceChildren();
 if(!data.findings.length)$("findings").append(element("p","No findings in the retained run window. Check source status before interpreting an empty result."));
 for(const finding of data.findings){const item=element("article"),button=element("button",`${finding.rule} [${finding.category}]`);button.onclick=()=>inspect(finding.title,finding.explanation,data.evidence.filter(e=>finding.evidence_ids.includes(e.id)));item.append(button,element("p",finding.explanation),element("small",`${finding.source} · ${finding.count} supporting observations · pack ${finding.rule_pack||"datacenter-v1"}`));$("findings").append(item);}
 $("flows").replaceChildren();
 for(const flow of data.flows.slice(-12).reverse()){const row=element("tr"),cell=element("td"),button=element("button",new Date(flow.ts*1000).toLocaleTimeString());button.onclick=()=>inspect("Zeek connection",`${flow.src} → ${flow.dst}:${flow.port}`,flow.raw);cell.append(button);row.append(cell);[flow.src,flow.dst,flow.port,flow.state,flow.bytes].forEach(v=>row.append(element("td",String(v))));$("flows").append(row);}
 $("gpu").textContent=JSON.stringify({latest_sample:data.gpu.at(-1)||null,model:data.model},null,2);
 $("framework").textContent=JSON.stringify(data.framework||{},null,2);
}
async function control(mode,newRun=false){if(!snapshot?.control_token)return;const buttons=["start","apply","stop"].map($);buttons.forEach(b=>b.disabled=true);try{const response=await fetch("/api/control",{method:"POST",headers:{"Content-Type":"application/json","X-Lab-Token":snapshot.control_token},body:JSON.stringify({mode,new_run:newRun})});if(!response.ok)throw Error(`Control rejected (${response.status})`);error(null);}catch(e){error(e.message);}finally{buttons.forEach(b=>b.disabled=false);}}
$("start").onclick=()=>control("guided",true);$("apply").onclick=()=>control($("scenario").value);$("stop").onclick=()=>control("baseline");$("close").onclick=()=>$("evidence").close();
async function poll(){try{const response=await fetch("/api/state",{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error(`HTTP ${response.status}`);render(await response.json());}catch(e){error(`Connection failed; displayed records may be stale. ${e.message}`);}finally{setTimeout(poll,1500);}}
poll();
