import {test,expect} from "@playwright/test";
import {waitForTraceWindowEnd} from "../../journeys/helpers/trace-window";

async function windowFixture(page: import("@playwright/test").Page) {
  await page.setContent('<div data-testid="research-trace-scroll" style="height:100px;overflow-y:auto"><div style="height:10000px"><div id="rows"><button>first</button><button>second</button></div></div></div>');
  await page.getByTestId("research-trace-scroll").evaluate((el:HTMLElement)=>{el.scrollTop=el.scrollHeight;});
}

test("trace settlement: scroll geometry alone cannot pass before rows update",async({page})=>{
  await windowFixture(page);
  await page.evaluate(()=>{
    setTimeout(()=>{document.querySelector('#rows')!.innerHTML='<button>penultimate</button><button>last</button>';},150);
  });
  await waitForTraceWindowEnd(page,{firstLabel:"first",lastLabel:"last",timeoutMs:1000});
  // Deliberately immediate: an assertion that auto-waits would hide the bug
  // in the waiter being tested. This is a fake DOM control, not product data.
  expect(await page.locator('#rows').textContent()).toBe("penultimatelast");
});

test("trace settlement: stale rows fail within the original supplied budget",async({page})=>{
  await windowFixture(page);
  await expect(waitForTraceWindowEnd(page,{firstLabel:"first",lastLabel:"last",timeoutMs:100})).rejects.toThrow(/Timeout/);
});
