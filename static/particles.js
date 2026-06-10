(function(){
  // Canvas is already declared in the HTML with id="particles-canvas"
  var canvas = document.getElementById('particles-canvas');
  if (!canvas) return; // safety guard

  var ctx   = canvas.getContext('2d');
  var W, H;
  var mouse = { x: -9999, y: -9999 };

  // Antigravity warm palette: red → orange → yellow
  var PALETTE = [
    '#e83535','#e84a2e','#e86028','#e87522','#e88b1c',
    '#e8a016','#e8b610','#e8cb0a','#e8df05','#e8e800'
  ];

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function Particle() { this.init(true); }
  Particle.prototype.init = function(rand) {
    this.x     = Math.random() * W;
    this.y     = rand ? Math.random() * H : H + 12;
    this.vx    = (Math.random() - 0.5) * 0.6;
    this.vy    = -(Math.random() * 0.5 + 0.15);
    this.w     = Math.random() * 7 + 3;
    this.h     = Math.random() * 2.5 + 1;
    this.angle = Math.random() * Math.PI * 2;
    this.spin  = (Math.random() - 0.5) * 0.02;
    this.alpha = Math.random() * 0.6 + 0.3;
    this.color = PALETTE[Math.floor(Math.random() * PALETTE.length)];
    this.life  = 1;
    this.decay = Math.random() * 0.0012 + 0.0004;
  };
  Particle.prototype.update = function() {
    var dx   = mouse.x - this.x;
    var dy   = mouse.y - this.y;
    var dist = Math.sqrt(dx*dx + dy*dy) || 1;
    if (dist < 350) {
      var f = (350 - dist) / 350;
      var attract = f * f * 0.6;
      this.vx += (dx / dist) * attract;
      this.vy += (dy / dist) * attract;
      this.vx += (-dy / dist) * f * 0.25;
      this.vy += ( dx / dist) * f * 0.25;
      if (dist < 30) {
        var push = (30 - dist) / 30;
        this.vx -= (dx / dist) * push * 1.5;
        this.vy -= (dy / dist) * push * 1.5;
      }
    }
    this.vx  = this.vx * 0.94 + (Math.random()-0.5)*0.05;
    this.vy  = this.vy * 0.94 - 0.03;
    this.x  += this.vx;
    this.y  += this.vy;
    this.angle += this.spin;
    this.life  -= this.decay;
    if (this.x < -30) this.x = W+30;
    if (this.x > W+30) this.x = -30;
    if (this.y < -30 || this.life <= 0) this.init(false);
  };
  Particle.prototype.draw = function() {
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.rotate(this.angle);
    ctx.globalAlpha = this.alpha * this.life;
    ctx.fillStyle   = this.color;
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(-this.w/2, -this.h/2, this.w, this.h, 1);
    } else {
      ctx.rect(-this.w/2, -this.h/2, this.w, this.h);
    }
    ctx.fill();
    ctx.restore();
  };

  var particles = [];

  function init() {
    resize();
    for (var i=0; i<350; i++) particles.push(new Particle());
    loop();
  }

  function loop() {
    ctx.clearRect(0,0,W,H);
    for (var i=0; i<particles.length; i++) {
      particles[i].update();
      particles[i].draw();
    }
    requestAnimationFrame(loop);
  }

  window.addEventListener('resize',    resize);
  window.addEventListener('mousemove', function(e){ mouse.x=e.clientX; mouse.y=e.clientY; });
  window.addEventListener('mouseout',  function(){ mouse.x=-9999; mouse.y=-9999; });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
