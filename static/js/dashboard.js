// small helper to animate numbers (simple increment)
(function () {
  function animateValue(id, start, end, duration) {
    const el = document.getElementById(id);
    if (!el) return;
    const range = end - start;
    let startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      const value = Math.floor(start + range * progress);
      el.textContent = id === 'revenue' ? '$' + value : value;
      if (progress < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const orders = parseInt(document.getElementById('orders')?.textContent || '0', 10);
    const products = parseInt(document.getElementById('products')?.textContent || '0', 10);
    const revenueText = document.getElementById('revenue')?.textContent || '$0';
    const revenue = parseInt(revenueText.replace(/[^0-9]/g, ''), 10) || 0;
    animateValue('orders', 0, orders, 900);
    animateValue('products', 0, products, 900);
    animateValue('revenue', 0, revenue, 900);
  });
})();

// Reveal on scroll + gauge animation
(function(){
  function revealObserver() {
    const els = Array.from(document.querySelectorAll('.reveal'));
    if (!els.length) return;
    const io = new IntersectionObserver((entries)=>{
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
    }, {threshold:0.12});
    els.forEach(el=>io.observe(el));
  }

  function animateGauge() {
    const svg = document.getElementById('gauge');
    if (!svg) return;
    const lines = Array.from(svg.querySelectorAll('line'));
    lines.forEach((ln, i) => {
      ln.style.opacity = 0;
      ln.style.transition = 'opacity 420ms ease ' + (i * 18) + 'ms, transform 420ms ease ' + (i * 18) + 'ms';
      ln.style.transformOrigin = '115px 118px';
      ln.style.transform = 'scaleY(0.6)';
      setTimeout(()=>{
        ln.style.opacity = 1;
        ln.style.transform = 'scaleY(1)';
      }, 50 + i * 18);
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    revealObserver();
    // animate gauge after a short delay so it's visible
    setTimeout(animateGauge, 300);
  });
})();

