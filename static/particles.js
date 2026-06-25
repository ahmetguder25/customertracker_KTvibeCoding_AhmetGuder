(function(){
  var canvas = document.getElementById('particles-canvas');
  if (!canvas) return;

  var ctx = canvas.getContext('2d');
  var W, H;
  var mouse  = { x: -9999, y: -9999, active: false };
  // Group center — smoothly follows the cursor
  var center = { x: 0, y: 0 };

  // Antigravity blue-purple palette
  var PALETTE = [
    '#5B6EE1', '#6366F1', '#7C6FF7', '#8B5CF6', '#A78BFA',
    '#818CF8', '#4F46E5', '#6D5BF5', '#9584F9', '#7E73E8'
  ];

  var NUM_PARTICLES = 220;
  var CLOUD_RADIUS  = 260;  // radius of the circular cloud

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
    if (!mouse.active) {
      center.x = W / 2;
      center.y = H / 2;
    }
  }

  function Particle() {
    // Position within the cloud (offset from center)
    // Distribute in a disc shape (sqrt for uniform area distribution)
    var r     = Math.sqrt(Math.random()) * CLOUD_RADIUS;
    var theta = Math.random() * Math.PI * 2;
    this.offsetX = Math.cos(theta) * r;
    this.offsetY = Math.sin(theta) * r;

    // Each dot trails at its own speed — further dots lag more
    this.lag = 0.02 + (r / CLOUD_RADIUS) * 0.04;

    // Individual slow drift/wobble
    this.driftAngle  = Math.random() * Math.PI * 2;
    this.driftSpeed  = Math.random() * 0.006 + 0.002;
    this.driftRadius = Math.random() * 12 + 4;

    // Current drawn position (will lerp toward target)
    this.x = 0;
    this.y = 0;

    // Shape: elongated dash
    this.w     = Math.random() * 6 + 3;
    this.h     = Math.random() * 2 + 1;
    this.angle = Math.random() * Math.PI * 2;
    this.spin  = (Math.random() - 0.5) * 0.01;

    // Appearance
    this.alpha = Math.random() * 0.5 + 0.25;
    this.color = PALETTE[Math.floor(Math.random() * PALETTE.length)];
  }

  Particle.prototype.update = function() {
    // Individual wobble
    this.driftAngle += this.driftSpeed;
    var wobbleX = Math.cos(this.driftAngle) * this.driftRadius;
    var wobbleY = Math.sin(this.driftAngle * 0.7) * this.driftRadius;

    // Target = group center + cloud offset + wobble
    var targetX = center.x + this.offsetX + wobbleX;
    var targetY = center.y + this.offsetY + wobbleY;

    // Smooth follow with per-dot lag (creates the trailing cloud feel)
    this.x += (targetX - this.x) * this.lag;
    this.y += (targetY - this.y) * this.lag;

    // Slow rotation
    this.angle += this.spin;
  };

  Particle.prototype.draw = function() {
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.rotate(this.angle);
    ctx.globalAlpha = this.alpha;
    ctx.fillStyle   = this.color;
    ctx.beginPath();
    if (ctx.roundRect) {
      ctx.roundRect(-this.w / 2, -this.h / 2, this.w, this.h, 0.8);
    } else {
      ctx.rect(-this.w / 2, -this.h / 2, this.w, this.h);
    }
    ctx.fill();
    ctx.restore();
  };

  var particles = [];

  function init() {
    resize();
    center.x = W / 2;
    center.y = H / 2;
    for (var i = 0; i < NUM_PARTICLES; i++) {
      var p = new Particle();
      // Start at their target position so there's no initial "fly-in"
      p.x = center.x + p.offsetX;
      p.y = center.y + p.offsetY;
      particles.push(p);
    }
    loop();
  }

  function loop() {
    // Smoothly move group center toward cursor
    if (mouse.active) {
      center.x += (mouse.x - center.x) * 0.06;
      center.y += (mouse.y - center.y) * 0.06;
    } else {
      // Drift back to page center when mouse leaves
      center.x += (W / 2 - center.x) * 0.02;
      center.y += (H / 2 - center.y) * 0.02;
    }

    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < particles.length; i++) {
      particles[i].update();
      particles[i].draw();
    }
    requestAnimationFrame(loop);
  }

  window.addEventListener('resize', resize);
  window.addEventListener('mousemove', function(e) {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
    mouse.active = true;
  });
  window.addEventListener('mouseout', function() {
    mouse.active = false;
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
