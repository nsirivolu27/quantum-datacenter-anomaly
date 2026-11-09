/* The book is readable HTML without JavaScript. This adds page turns and local play. */
(() => {
  'use strict';
  const pages = [...document.querySelectorAll('.page')];
  const previous = document.querySelector('#previous');
  const next = document.querySelector('#next');
  const previousBar = document.querySelector('#previous-bar');
  const nextBar = document.querySelector('#next-bar');
  const counter = document.querySelector('#counter');
  const progress = document.querySelector('#progress');
  const contents = document.querySelector('#contents');
  const readButton = document.querySelector('#read-aloud');
  let current = 0;
  let reading = false;
  let utterance = null;

  function stopReading() {
    if (utterance) {
      utterance.onend = null;
      utterance.onerror = null;
      utterance = null;
    }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    reading = false;
    readButton.textContent = 'Read aloud';
    readButton.setAttribute('aria-pressed', 'false');
  }

  function showPage(moveFocus = false) {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { id = ''; }
    const found = pages.findIndex(page => page.id === id);
    current = found < 0 ? 0 : found;
    stopReading();
    pages.forEach((page, index) => {
      page.hidden = index !== current;
      page.classList.remove('settle');
    });
    void pages[current].offsetWidth; // restart the settle animation on every turn
    pages[current].classList.add('settle');
    previous.disabled = previousBar.disabled = current === 0;
    next.disabled = nextBar.disabled = current === pages.length - 1;
    counter.textContent = `Page ${current + 1} of ${pages.length}`;
    progress.value = current + 1;
    document.title = `${pages[current].dataset.title} · Where Does My Picture Go?`;
    contents.querySelectorAll('a').forEach(link => {
      if (link.hash === `#${pages[current].id}`) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (moveFocus) {
      pages[current].querySelector('h1,h2').focus({preventScroll: true});
      window.scrollTo({top: 0, behavior: 'instant'});
    }
  }

  function turn(delta) {
    const target = pages[current + delta];
    if (target) location.hash = target.id;
  }

  [previous, previousBar].forEach(item => item.addEventListener('click', () => turn(-1)));
  [next, nextBar].forEach(item => item.addEventListener('click', () => turn(1)));
  window.addEventListener('hashchange', () => showPage(true));
  document.querySelector('.skip').addEventListener('click', event => {
    event.preventDefault();
    pages[current].querySelector('h1,h2').focus();
  });
  document.addEventListener('keydown', event => {
    if (contents.open || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.target.closest('button,input,select,textarea,a,[contenteditable]')) return;
    if (event.key === 'ArrowRight') { event.preventDefault(); turn(1); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); turn(-1); }
  });
  document.querySelector('#open-contents').addEventListener('click', () => contents.showModal());
  document.querySelector('#close-contents').addEventListener('click', () => contents.close());
  contents.addEventListener('click', event => {
    if (event.target.closest('a')) {
      contents.close();
      // The hash may already match; focus the page even in that case.
      setTimeout(() => pages[current].querySelector('h1,h2').focus({preventScroll: true}), 0);
    }
  });

  if ('speechSynthesis' in window && 'SpeechSynthesisUtterance' in window) {
    readButton.hidden = false;
    readButton.addEventListener('click', () => {
      if (reading) { stopReading(); return; }
      const page = pages[current];
      const words = [page.dataset.title, ...[...page.querySelectorAll('.story p,.ask,.words dt,.words dd,.sources-list a,.sources-list p')].map(node => node.textContent)];
      utterance = new SpeechSynthesisUtterance(words.join('. '));
      utterance.lang = 'en-US';
      utterance.rate = .85;
      const voice = window.speechSynthesis.getVoices().find(item => item.lang.startsWith('en') && item.localService);
      if (voice) utterance.voice = voice;
      utterance.onend = stopReading;
      utterance.onerror = event => {
        stopReading();
        if (!['canceled','interrupted'].includes(event.error)) document.querySelector('#voice-status').textContent = 'Read aloud is unavailable on this device. You can read together or use a screen reader.';
      };
      reading = true;
      readButton.textContent = 'Stop reading';
      readButton.setAttribute('aria-pressed', 'true');
      document.querySelector('#voice-status').textContent = '';
      window.speechSynthesis.speak(utterance);
    });
  }
  window.addEventListener('pagehide', stopReading);

  function button(label, callback) {
    const element = document.createElement('button');
    element.type = 'button';
    element.textContent = label;
    element.addEventListener('click', () => callback(element));
    return element;
  }
  function stage(container, initial) {
    const art = document.createElement('div'); art.className = 'mini-art'; art.setAttribute('aria-hidden', 'true');
    const buttons = document.createElement('div'); buttons.className = 'buttons';
    const feedback = document.createElement('p'); feedback.className = 'feedback'; feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-atomic', 'true'); feedback.textContent = initial;
    container.append(art, buttons, feedback);
    return {art, buttons, feedback};
  }
  function whale(changed = false) {
    return `<svg viewBox="0 0 140 85" aria-hidden="true"><path d="M18 45Q25 23 62 32Q89 36 99 59Q117 47 124 38L129 59Q115 74 93 69Q55 87 26 66Z" fill="#397f9a"/><circle cx="35" cy="46" r="3" fill="#233a40"/>${changed ? '<circle cx="108" cy="16" r="12" fill="#ad4834"/>' : '<path d="M108 2L112 12L123 12L115 19L118 30L108 24L98 30L101 19L93 12L104 12Z" fill="#e8b84e"/>'}</svg>`;
  }
  function choices(container, initial, options) {
    const ui = stage(container, initial); ui.art.remove();
    options.forEach(([label, message]) => ui.buttons.append(button(label, selected => {
      [...ui.buttons.children].forEach(item => item.setAttribute('aria-pressed', String(item === selected)));
      ui.feedback.textContent = message;
    })));
  }

  document.querySelectorAll('[data-activity]').forEach(container => {
    const kind = container.dataset.activity;
    if (kind === 'packets') {
      const ui = stage(container, 'Three pieces are waiting.');
      for (let i = 1; i <= 3; i++) {
        const packet = document.createElement('span'); packet.className = 'packet'; packet.textContent = i; ui.art.append(packet);
        ui.buttons.append(button(`Send piece ${i}`, selected => {
          packet.classList.add('arrived'); selected.disabled = true;
          const count = ui.art.querySelectorAll('.arrived').length;
          ui.feedback.textContent = count === 3 ? 'All three pieces arrived. The picture fits together!' : `${count} of 3 pieces arrived. Keep going!`;
        }));
      }
      ui.buttons.append(button('Again', () => {
        ui.art.querySelectorAll('.packet').forEach(item => item.classList.remove('arrived'));
        [...ui.buttons.children].forEach(item => { item.disabled = false; });
        ui.feedback.textContent = 'Three pieces are waiting.';
      }));
    } else if (kind === 'gpu') {
      const ui = stage(container, 'Many little jobs can happen together.');
      const grid = document.createElement('div'); grid.className = 'tile-grid';
      for (let i = 0; i < 18; i++) grid.append(document.createElement('i'));
      ui.art.append(grid);
      ui.buttons.append(button('Work together', selected => {
        const lit = grid.classList.toggle('lit'); selected.textContent = lit ? 'Try again' : 'Work together';
        ui.feedback.textContent = lit ? 'Look! Lots of squares changed at once. GPUs help with jobs like this.' : 'Many little jobs can happen together.';
      }));
    } else if (kind === 'metrics') {
      choices(container, 'Pick a clue.', [['Busy','Utilization means how busy the GPU is. Busy can be okay.'],['Heat','Temperature tells us how warm it is. The team checks cooling.'],['Power','Power tells us how fast the GPU uses electrical energy.'],['Room','Memory holds things the GPU is working on. The team checks how much is in use.']]);
    } else if (kind === 'cooling') {
      const ui = stage(container, 'Our pretend computer is too warm.');
      ui.art.innerHTML = '<div class="air">WARM · → → →</div>';
      ui.buttons.append(button('Let the team fix the fan', selected => {
        ui.art.firstChild.classList.add('fixed'); ui.art.firstChild.textContent = 'COOLER · → → →';
        ui.feedback.textContent = 'Whoosh! In our story, the repaired fan carries heat away.'; selected.disabled = true;
      }));
      ui.buttons.append(button('Start again', () => {
        ui.art.firstChild.classList.remove('fixed'); ui.art.firstChild.textContent = 'WARM · → → →'; ui.buttons.firstChild.disabled = false;
        ui.feedback.textContent = 'Our pretend computer is too warm.';
      }));
    } else if (kind === 'permission') {
      choices(container, 'Grandpa may look at the picture.', [['Look','Yes. Maya gave Grandpa permission to look.'],['Change','That needs a different permission. Looking does not mean changing.']]);
    } else if (kind === 'encryption') {
      const ui = stage(container, 'This screen cover is only a pretend lock.');
      const box = document.createElement('div'); box.className = 'picture-box'; box.textContent = 'CLOSED'; ui.art.append(box);
      ui.buttons.append(button('Use pretend key', selected => {
        const opened = box.dataset.open !== 'yes'; box.dataset.open = opened ? 'yes' : 'no';
        box.innerHTML = opened ? whale() : 'CLOSED'; selected.textContent = opened ? 'Close the box' : 'Use pretend key';
        ui.feedback.textContent = opened ? 'There is the whale. Real encryption uses math and digital keys.' : 'Our pretend box is closed again. This activity does not encrypt data.';
      }));
    } else if (kind === 'clue') {
      choices(container, 'A different pattern is a clue.', [['Check the clues','Yes. Check the work and the logs before deciding.'],['Call it bad at once','We do not know yet. Busy work, mistakes, and unsafe activity can look alike.']]);
    } else if (kind === 'change') {
      choices(container, 'Look at the two pictures in the illustration.', [['The sky shape','You found it! The star became a circle. Now the team checks why.'],['The whale','Look above the whale. The shape in the sky has changed.']]);
    } else if (kind === 'restore') {
      const ui = stage(container, 'This copy has a circle. A checked backup has the star.');
      const box = document.createElement('div'); box.className = 'picture-box'; box.innerHTML = whale(true); ui.art.append(box);
      ui.buttons.append(button('Use the checked backup', selected => {
        box.innerHTML = whale(); ui.feedback.textContent = 'The star is back. The team still investigates the cause.'; selected.disabled = true;
      }));
      ui.buttons.append(button('Try again', () => {
        box.innerHTML = whale(true); ui.buttons.firstChild.disabled = false; ui.feedback.textContent = 'This copy has a circle. A checked backup has the star.';
      }));
    } else if (kind === 'help') {
      choices(container, 'You do not need to share your address here.', [['Pause and ask a grown-up','Yes. Ask a trusted grown-up to help. You can ask even if you already clicked.'],['Type my address','Keep private information private. Pause and ask a trusted grown-up first.']]);
    } else if (kind === 'journey') {
      const ui = stage(container, 'First, where does the picture start?'); ui.art.remove();
      let step = 0;
      const stops = ['Maya’s tablet','Data center','Grandpa’s screen'];
      [2,0,1].forEach(index => ui.buttons.append(button(stops[index], selected => {
        if (index !== step) { ui.feedback.textContent = step === 0 ? 'Start with Maya and her drawing.' : 'Think about the next stop in our story. Try another.'; return; }
        step++; selected.disabled = true;
        ui.feedback.textContent = step === 3 ? 'Maya → data center → Grandpa. You told the journey!' : step === 1 ? 'Yes! Now choose the building that helps.' : 'Yes! Who gets to see the picture?';
      })));
      ui.buttons.append(button('Start again', () => { step = 0; [...ui.buttons.children].forEach(item => { item.disabled = false; }); ui.feedback.textContent = 'First, where does the picture start?'; }));
    } else if (kind === 'doors') {
      choices(container, 'Find the request that has no permission.', [['Grandpa looks','Grandpa has permission to look. His request is allowed.'],['Rae checks','Rae has permission to check the backup. Her request is allowed.'],['Someone erases','That request has no permission. Keep it closed and ask the team to check.']]);
    }
  });
  document.documentElement.classList.add('js');
  document.querySelector('#open-contents').hidden = false;
  showPage();
})();
