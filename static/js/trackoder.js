document.addEventListener('DOMContentLoaded', function(){
  // animate progress bar: start from 0, then expand to data width
  const bars = Array.from(document.querySelectorAll('.card .bg-brand-600'));
  bars.forEach(bar => {
    const target = bar.style.width || bar.getAttribute('data-width') || '';
    // normalize like "65%"
    const computed = target || bar.getAttribute('style')?.match(/width:\s*([^;]+)/)?.[1] || '';
    // set to 0 then force reflow and set to target
    bar.style.width = '0%';
    // small timeout to ensure transition
    setTimeout(()=>{ bar.style.width = computed || '0%'; }, 40);
  });

  // reveal on scroll (simple)
  const els = Array.from(document.querySelectorAll('.reveal'));
  if (els.length) {
    const io = new IntersectionObserver((entries)=>{
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
    }, {threshold:0.12});
    els.forEach(el=>io.observe(el));
  }
});
