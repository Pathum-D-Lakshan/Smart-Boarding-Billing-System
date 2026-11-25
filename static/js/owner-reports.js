/* Plotting uses Numbers only for SVG coordinates; all displayed money comes from the server. */
(() => {
    const target=document.getElementById('reports-chart');
    const payload=document.getElementById('reports-chart-data');
    const tooltip=document.getElementById('reports-chart-tooltip');
    if (!target || !payload || !tooltip) return;
    let rows;
    try { rows=JSON.parse(payload.textContent); } catch { tooltip.textContent='The chart could not be loaded. Use the comparison table below.';return; }
    if (!Array.isArray(rows) || !rows.length || rows.length>12 || rows.some(row=>['income','expenses','balance'].some(key=>!Number.isFinite(Number(row[key]))))) {
        tooltip.textContent='No valid chart data. The comparison table remains available.';return;
    }
    let lastWidth=0;
    function render() {
    const balance=target.dataset.trend==='balance';
    const series=balance ? [['balance','Net Balance']] : [['income','Collected Income'],['expenses','Actual Expenses']];
    const values=rows.flatMap(row=>series.map(([key])=>Number(row[key])));
    const low=Math.min(0,...values),high=Math.max(0,...values);
    const floor=low<0 ? low*1.12 : 0,ceiling=high>0 ? high*1.12 : low<0 ? 0 : 1;
    const width=Math.max(320,Math.min(1200,target.clientWidth||900));lastWidth=width;
    const narrow=width<500;
    const height=410,left=narrow?76:100,right=narrow?20:26,top=narrow?88:65,bottom=65;
    const plotWidth=width-left-right,plotHeight=height-top-bottom;
    const x=index=>left+(rows.length===1 ? plotWidth/2 : index*plotWidth/(rows.length-1));
    const y=value=>top+(ceiling-value)*plotHeight/(ceiling-floor);
    function element(tag,attributes={},text='') {
        const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
        for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,String(value));
        if (text) node.textContent=text;
        return node;
    }
    const svg=element('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':balance?'Monthly Net Balance line chart':'Monthly Collected Income and Actual Expenses line chart'});
    svg.append(element('title',{},balance?'Net Balance by month':'Collected Income vs Actual Expenses by month'));
    svg.append(element('text',{x:12,y:47},'LKR'));
    const compact=value=>new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(value);
    for (let tick=0;tick<=5;tick++) {
        const value=floor+(ceiling-floor)*tick/5,position=y(value);
        svg.append(element('line',{x1:left,y1:position,x2:width-right,y2:position,class:'chart-grid'}));
        svg.append(element('text',{x:left-12,y:position+5,'text-anchor':'end'},compact(value)));
    }
    svg.append(element('line',{x1:left,y1:y(0),x2:width-right,y2:y(0),class:'chart-zero'}));
    rows.forEach((row,index)=>{
        const label=String(row.label);
        if (index%Math.ceil(rows.length/(narrow?3:6))===0 || index===rows.length-1)
            svg.append(element('text',{x:x(index),y:height-33,'text-anchor':'middle'},narrow?label.replace(/^(\w{3})\w* \d{2}(\d{2})$/,'$1 $2'):label.replace(/^(\w{3})\w* /,'$1 ')));
    });
    svg.append(element('text',{x:left+plotWidth/2,y:height-8,'text-anchor':'middle'},'Month'));
    series.forEach(([key,label],seriesIndex)=>{
        const legendX=left+(narrow?0:seriesIndex*250),legendY=narrow?24+seriesIndex*25:25;
        svg.append(element('line',{x1:legendX,y1:legendY,x2:legendX+30,y2:legendY,class:'chart-line chart-'+key}));
        svg.append(element('text',{x:legendX+40,y:legendY+5},label));
        const path=rows.map((row,index)=>(index?'L':'M')+x(index)+','+y(Number(row[key]))).join(' ');
        svg.append(element('path',{d:path,class:'chart-line chart-'+key}));
        rows.forEach((row,index)=>{
            const message=String(row.label)+' - '+label+': LKR '+String(row[key+'_formatted']);
            const point=element('circle',{cx:x(index),cy:y(Number(row[key])),r:5,tabindex:0,
                class:'chart-point chart-'+key+(Number(row[key])<0?' chart-negative':''),'aria-label':message});
            point.append(element('title',{},message));
            for (const event of ['focus','mouseenter','pointerdown']) point.addEventListener(event,()=>{tooltip.textContent=message;});
            svg.append(point);
        });
    });
    target.replaceChildren(svg);
    if (values.every(value=>value===0)) tooltip.textContent='No financial records in this interval. All monthly totals are zero.';
    }
    render();
    if (typeof ResizeObserver==='function') new ResizeObserver(()=>{
        const width=Math.max(320,Math.min(1200,target.clientWidth||900));if(width!==lastWidth)render();
    }).observe(target);
    else if(typeof window!=='undefined') window.addEventListener('resize',render);
})();
