import type {Page} from "@playwright/test";

/** Wait for the virtualized rows, not only synchronous scroll geometry. */
export async function waitForTraceWindowEnd(page:Page, options:{firstLabel:string;lastLabel:string;timeoutMs:number}):Promise<void> {
  if(!options.firstLabel || !options.lastLabel || options.firstLabel===options.lastLabel) throw new Error("Distinct trace boundary labels are required");
  await page.waitForFunction(({firstLabel,lastLabel})=>{
    const el=document.querySelector('[data-testid="research-trace-scroll"]') as HTMLElement|null;
    if(!el || el.scrollTop+el.clientHeight<el.scrollHeight-1) return false;
    const labels=Array.from(el.querySelectorAll('button'),button=>(button.textContent??'').trim());
    return labels.includes(lastLabel)&&!labels.includes(firstLabel);
  },{firstLabel:options.firstLabel,lastLabel:options.lastLabel},{timeout:options.timeoutMs});
}
