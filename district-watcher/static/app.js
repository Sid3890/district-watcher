// District Watcher Dashboard — Frontend Application & Web Audio Synthesizer

(function () {
  'use strict';

  // State
  const state = {
    settings: {
      sound_enabled: true,
      sound_tone: 'chime',
      sound_volume: 0.8,
      desktop_notifications_enabled: true,
      poll_interval_seconds: 45,
      last_selected_city: 'Chennai',
    },
    currentCity: 'Chennai',
    movies: [],
    selectedMovie: null,
    theatres: [],
    availableDates: [],
    selectedTheatre: null,
    selectedShowtime: null,
    seatMap: null,
    selectedSeats: new Set(),
    activeWatches: [],
    currentMode: 'SHOW_OPENING',
    audioCtx: null,
  };

  // DOM Elements
  const silenceAlarmBtn = document.getElementById('silence-alarm-btn');
  const soundToggleBtn = document.getElementById('sound-toggle-btn');
  const soundToggleLabel = document.getElementById('sound-toggle-label');
  const soundIcon = document.getElementById('sound-icon');
  const soundToneSelect = document.getElementById('sound-tone-select');
  const soundVolumeSlider = document.getElementById('sound-volume-slider');
  const armAudioBtn = document.getElementById('arm-audio-btn');
  const selectAllSoldBtn = document.getElementById('select-all-sold-btn');

  const citySelect = document.getElementById('city-select');
  const movieSelect = document.getElementById('movie-select');
  const movieFetchIndicator = document.getElementById('movie-fetch-indicator');
  const targetDateInput = document.getElementById('target-date-input');
  const availableDatesBox = document.getElementById('available-dates-box');
  const availableDatesPills = document.getElementById('available-dates-pills');
  const theatreSelect = document.getElementById('theatre-select');
  const customTheatreInput = document.getElementById('custom-theatre-input');
  const refreshShowsBtn = document.getElementById('refresh-shows-btn');
  const theatreFetchIndicator = document.getElementById('theatre-fetch-indicator');

  const directMovieUrl = document.getElementById('direct-movie-url');
  const directMovieTitle = document.getElementById('direct-movie-title');
  const loadDirectMovieBtn = document.getElementById('load-direct-movie-btn');

  const tabMode1 = document.getElementById('tab-mode-1');
  const tabMode2 = document.getElementById('tab-mode-2');
  const mode1Panel = document.getElementById('mode-1-panel');
  const mode2Panel = document.getElementById('mode-2-panel');
  const prefTimeFilter = document.getElementById('pref-time-filter');
  const startMode1Btn = document.getElementById('start-mode-1-btn');

  const showtimePills = document.getElementById('showtime-pills');
  const loadSeatMapBtn = document.getElementById('load-seat-map-btn');
  const seatMapLoading = document.getElementById('seat-map-loading');
  const seatMapContainer = document.getElementById('seat-map-container');
  const seatGridContent = document.getElementById('seat-grid-content');
  const selectedSeatsChips = document.getElementById('selected-seats-chips');
  const startMode2Btn = document.getElementById('start-mode-2-btn');
  const screenLabel = document.getElementById('screen-label');

  const watchesList = document.getElementById('watches-list');
  const refreshWatchesBtn = document.getElementById('refresh-watches-btn');
  const statActiveWatches = document.getElementById('stat-active-watches');
  const statAlertsFired = document.getElementById('stat-alerts-fired');
  const alertHistoryList = document.getElementById('alert-history-list');

  const alertModal = document.getElementById('alert-modal');
  const modalAlertTitle = document.getElementById('modal-alert-title');
  const modalAlertType = document.getElementById('modal-alert-type');
  const modalAlertMessage = document.getElementById('modal-alert-message');
  const modalBookBtn = document.getElementById('modal-book-btn');
  const modalAckBtn = document.getElementById('modal-ack-btn');

  let currentActiveAlert = null;

  // ==========================================
  // 1. Web Audio API Synthesizer
  // ==========================================
  function initAudioContext() {
    if (!state.audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        state.audioCtx = new AudioContextClass();
      }
    }
    if (state.audioCtx && state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
      armAudioBtn.classList.add('hidden');
    }
  }

  function checkAudioState() {
    if (state.audioCtx && state.audioCtx.state === 'suspended') {
      armAudioBtn.classList.remove('hidden');
    } else {
      armAudioBtn.classList.add('hidden');
    }
  }

  function playAlertSound(toneType, volume = 0.8) {
    if (!state.settings.sound_enabled) return;
    initAudioContext();
    if (!state.audioCtx) return;

    const ctx = state.audioCtx;
    const now = ctx.currentTime;
    const tone = toneType || state.settings.sound_tone || 'chime';
    const vol = Math.max(0.01, Math.min(1.0, volume !== undefined ? volume : state.settings.sound_volume));

    if (tone === 'chime') {
      const notes = [523.25, 659.25, 783.99, 1046.50];
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, now + idx * 0.12);

        gain.gain.setValueAtTime(0, now + idx * 0.12);
        gain.gain.linearRampToValueAtTime(vol * 0.4, now + idx * 0.12 + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.12 + 0.6);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now + idx * 0.12);
        osc.stop(now + idx * 0.12 + 0.7);
      });
    } else if (tone === 'bell') {
      const notes = [880.0, 659.25];
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, now + idx * 0.22);

        gain.gain.setValueAtTime(0, now + idx * 0.22);
        gain.gain.linearRampToValueAtTime(vol * 0.5, now + idx * 0.22 + 0.03);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.22 + 0.9);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now + idx * 0.22);
        osc.stop(now + idx * 0.22 + 1.0);
      });
    } else if (tone === 'pulse') {
      for (let i = 0; i < 3; i++) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'square';
        osc.frequency.setValueAtTime(880, now + i * 0.18);

        gain.gain.setValueAtTime(vol * 0.35, now + i * 0.18);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.18 + 0.12);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now + i * 0.18);
        osc.stop(now + i * 0.18 + 0.14);
      }
    }
  }

  // ==========================================
  // 2. Settings Synchronization
  // ==========================================
  async function loadSettings() {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        state.settings = await res.json();
        updateSettingsUI();
      }
    } catch (e) {
      console.warn('Could not load settings:', e);
    }
  }

  function updateSettingsUI() {
    if (state.settings.sound_enabled) {
      soundToggleBtn.className = 'px-3 py-1.5 rounded-lg border text-sm font-semibold flex items-center space-x-2 transition-all shadow-sm bg-emerald-950/60 border-emerald-600 text-emerald-300 hover:bg-emerald-900/60';
      soundIcon.textContent = '🔊';
      soundToggleLabel.textContent = 'Sound Alert: ON';
    } else {
      soundToggleBtn.className = 'px-3 py-1.5 rounded-lg border text-sm font-semibold flex items-center space-x-2 transition-all shadow-sm bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700';
      soundIcon.textContent = '🔇';
      soundToggleLabel.textContent = 'Sound Alert: OFF';
    }
    soundToneSelect.value = state.settings.sound_tone || 'chime';
    soundVolumeSlider.value = state.settings.sound_volume !== undefined ? state.settings.sound_volume : 0.8;
  }

  async function saveSettings(updates) {
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        state.settings = await res.json();
        updateSettingsUI();
      }
    } catch (e) {
      console.error('Failed to update settings:', e);
    }
  }

  // ==========================================
  // 3. Movies & Theatres Loading
  // ==========================================
  async function fetchMovies(city) {
    state.currentCity = city;
    movieFetchIndicator.classList.remove('hidden');
    movieSelect.innerHTML = '<option value="">Scanning movies on District.in...</option>';
    try {
      const res = await fetch(`/api/movies?city=${encodeURIComponent(city)}`);
      if (res.ok) {
        state.movies = await res.json();
        populateMoviesDropdown();
      } else {
        movieSelect.innerHTML = '<option value="">Failed to load movies. Try custom URL below.</option>';
      }
    } catch (e) {
      console.error('Failed to fetch movies:', e);
      movieSelect.innerHTML = '<option value="">Network error loading movies.</option>';
    } finally {
      movieFetchIndicator.classList.add('hidden');
    }
  }

  function populateMoviesDropdown() {
    if (!state.movies || state.movies.length === 0) {
      movieSelect.innerHTML = '<option value="">No movies currently listed. Enter URL below.</option>';
      return;
    }
    let html = '<option value="">-- Select Movie (' + state.movies.length + ' available) --</option>';
    state.movies.forEach((m, idx) => {
      const fmt = m.formats && m.formats.length > 0 ? ` [${m.formats.join(', ')}]` : '';
      const upcoming = m.is_upcoming ? ' (Upcoming)' : '';
      html += `<option value="${idx}">${m.title}${fmt}${upcoming}</option>`;
    });
    movieSelect.innerHTML = html;
  }

  function renderAvailableDatePills(dates) {
    if (!dates || dates.length === 0) {
      availableDatesBox.classList.add('hidden');
      availableDatesPills.innerHTML = '';
      return;
    }

    availableDatesBox.classList.remove('hidden');
    let html = '';
    const currentTargetDate = targetDateInput.value;

    dates.forEach((dStr) => {
      // dStr is YYYY-MM-DD
      const dt = new Date(dStr + 'T00:00:00');
      const dayName = dt.toLocaleDateString('en-US', { weekday: 'short' });
      const monthName = dt.toLocaleDateString('en-US', { month: 'short' });
      const dayNum = dt.getDate();
      const isSelected = dStr === currentTargetDate;

      const activeClass = isSelected
        ? 'bg-emerald-600 text-white border-emerald-400 font-extrabold shadow-sm'
        : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700 hover:border-emerald-500';

      html += `
        <button type="button" class="date-chip px-2.5 py-1 rounded text-xs border font-mono transition flex items-center space-x-1 ${activeClass}" data-date="${dStr}">
          <span>${dayNum} ${monthName}</span>
          <span class="text-[10px] opacity-80">(${dayName})</span>
        </button>
      `;
    });

    availableDatesPills.innerHTML = html;

    // Attach click listeners to date pills
    availableDatesPills.querySelectorAll('.date-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const selectedDate = chip.getAttribute('data-date');
        targetDateInput.value = selectedDate;
        fetchTheatresAndShows();
      });
    });
  }

  async function fetchTheatresAndShows() {
    if (!state.selectedMovie || !targetDateInput.value) {
      return;
    }
    theatreFetchIndicator.classList.remove('hidden');
    theatreSelect.innerHTML = '<option value="">Loading showtimes...</option>';
    showtimePills.innerHTML = '<span class="text-xs text-cyan-400">Scanning showtimes...</span>';

    try {
      const url = `/api/shows?movie_url=${encodeURIComponent(state.selectedMovie.movie_url)}&date=${encodeURIComponent(targetDateInput.value)}&city=${encodeURIComponent(state.currentCity)}`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        state.theatres = data.theatres || [];
        state.availableDates = data.available_dates || [];

        renderAvailableDatePills(state.availableDates);

        // Auto-switch date if no theatres found for current date but available_dates exist
        if (state.theatres.length === 0 && state.availableDates.length > 0) {
          const isDateInAvailable = state.availableDates.includes(targetDateInput.value);
          if (!isDateInAvailable) {
            console.info(`Target date ${targetDateInput.value} has no shows. Auto-selecting first open date: ${state.availableDates[0]}`);
            targetDateInput.value = state.availableDates[0];
            return await fetchTheatresAndShows();
          }
        }

        populateTheatresDropdown();
      } else {
        theatreSelect.innerHTML = '<option value="">No open theatres found yet (Ideal for Mode 1 Watch!)</option>';
        showtimePills.innerHTML = '<span class="text-xs text-gray-500 italic">No open shows yet. Switch to Mode 1 to watch when bookings open!</span>';
      }
    } catch (e) {
      console.error('Failed to fetch theatres:', e);
      theatreSelect.innerHTML = '<option value="">Could not load shows. Enter theatre manually.</option>';
    } finally {
      theatreFetchIndicator.classList.add('hidden');
    }
  }

  function populateTheatresDropdown() {
    if (!state.theatres || state.theatres.length === 0) {
      theatreSelect.innerHTML = '<option value="">No theatres currently listed for this date (Use Mode 1 to monitor opening!)</option>';
      showtimePills.innerHTML = '<span class="text-xs text-amber-400 italic">No open theatres found for this date. Enter your expected cinema below for Mode 1!</span>';
      state.selectedTheatre = null;
      return;
    }
    let html = '<option value="">-- Choose Open Theatre (' + state.theatres.length + ' listed) --</option>';
    state.theatres.forEach((t, idx) => {
      const showCount = t.showtimes ? t.showtimes.length : 0;
      html += `<option value="${idx}">${t.theatre_name} (${showCount} shows)</option>`;
    });
    theatreSelect.innerHTML = html;

    // Automatically select the first theatre and show its times
    if (state.theatres.length > 0) {
      theatreSelect.value = "0";
      state.selectedTheatre = state.theatres[0];
      renderShowtimePills(state.selectedTheatre);
    }
  }

  function renderShowtimePills(theatre) {
    if (!theatre || !theatre.showtimes || theatre.showtimes.length === 0) {
      showtimePills.innerHTML = '<span class="text-xs text-gray-500 italic">No showtimes available for this cinema.</span>';
      return;
    }
    let html = '';
    theatre.showtimes.forEach((s) => {
      const isSoldOut = (s.avail_seats === 0) || (s.seat_status && s.seat_status.toLowerCase() === 'sold out');
      const statusBadge = isSoldOut 
        ? '<span class="text-[9px] px-1 py-0.2 rounded bg-red-950/80 text-red-300 border border-red-800 font-bold ml-1">FULL</span>' 
        : (s.seat_status && s.seat_status !== 'Available' ? `<span class="text-[9px] px-1 py-0.2 rounded bg-amber-950/80 text-amber-300 border border-amber-800 font-bold ml-1">${s.seat_status}</span>` : '');

      html += `
        <button type="button" class="showtime-pill px-3 py-1.5 rounded-lg border border-gray-700 bg-gray-800 hover:bg-cyan-950 hover:border-cyan-500 text-xs font-semibold text-gray-200 transition inline-flex items-center space-x-1" data-time="${s.time_str}" data-soldout="${isSoldOut}">
          <span>${s.time_str}</span>
          <span class="text-[10px] text-cyan-400 font-mono">${s.format_tag || '2D'}</span>
          ${statusBadge}
        </button>
      `;
    });
    showtimePills.innerHTML = html;

    const pills = showtimePills.querySelectorAll('.showtime-pill');
    pills.forEach((p) => {
      p.addEventListener('click', () => {
        pills.forEach((x) => {
          x.classList.remove('bg-cyan-600', 'border-cyan-400', 'text-white');
          x.classList.add('bg-gray-800', 'border-gray-700', 'text-gray-200');
        });
        p.classList.remove('bg-gray-800', 'border-gray-700', 'text-gray-200');
        p.classList.add('bg-cyan-600', 'border-cyan-400', 'text-white');
        state.selectedShowtime = p.getAttribute('data-time');
      });
    });

    if (pills.length > 0) {
      pills[0].click();
    }
  }

  // ==========================================
  // 4. Interactive Seat Map
  // ==========================================
  async function loadSeatMap() {
    if (!state.selectedMovie) {
      alert('Please select a movie first.');
      return;
    }
    const theatreName = (state.selectedTheatre && state.selectedTheatre.theatre_name) || customTheatreInput.value.trim();
    if (!theatreName) {
      alert('Please choose or enter a theatre name.');
      return;
    }
    if (!state.selectedShowtime) {
      alert('Please select a showtime pill.');
      return;
    }

    seatMapLoading.classList.remove('hidden');
    seatMapContainer.classList.add('hidden');
    state.selectedSeats.clear();
    renderSelectedSeatsChips();

    try {
      const res = await fetch('/api/seat-map', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          movie_url: state.selectedMovie.movie_url,
          date: targetDateInput.value,
          theatre_name: theatreName,
          showtime_str: state.selectedShowtime,
          city: state.currentCity || 'Chennai',
        }),
      });

      if (res.ok) {
        state.seatMap = await res.json();
        renderSeatGrid(state.seatMap);
        seatMapContainer.classList.remove('hidden');
      } else {
        const err = await res.json();
        alert('Failed to load seat map: ' + (err.detail || 'Unknown error'));
      }
    } catch (e) {
      console.error('Error loading seat map:', e);
      alert('Network error loading seat layout.');
    } finally {
      seatMapLoading.classList.add('hidden');
    }
  }

  function renderSeatGrid(seatMapData) {
    if (!seatMapData || !seatMapData.seats || seatMapData.seats.length === 0) {
      seatGridContent.innerHTML = '<p class="text-center text-gray-500 py-6">No seating data found.</p>';
      return;
    }

    screenLabel.textContent = `${seatMapData.screen_name || 'SCREEN 1'} — SCREEN THIS WAY`;

    const categoryMap = new Map();
    seatMapData.seats.forEach((s) => {
      const cat = s.category || 'STANDARD';
      if (!categoryMap.has(cat)) {
        categoryMap.set(cat, new Map());
      }
      const rowMap = categoryMap.get(cat);
      const row = s.row_label || 'A';
      if (!rowMap.has(row)) {
        rowMap.set(row, []);
      }
      rowMap.get(row).push(s);
    });

    let html = '';
    categoryMap.forEach((rowsMap, catName) => {
      html += `
        <div class="space-y-2 border-b border-gray-800 pb-3 mb-3">
          <div class="text-[11px] font-bold tracking-wider uppercase text-cyan-300 flex items-center justify-between">
            <span>${catName}</span>
            <span class="text-gray-400 font-mono">${rowsMap.values().next().value[0]?.price ? '₹' + rowsMap.values().next().value[0].price : ''}</span>
          </div>
      `;

      rowsMap.forEach((seatsList, rowLabel) => {
        html += `
          <div class="flex items-center space-x-2 justify-center">
            <span class="w-6 text-right text-xs font-bold text-gray-500 font-mono">${rowLabel}</span>
            <div class="flex flex-wrap items-center gap-1.5 justify-center">
        `;

        seatsList.forEach((seat) => {
          let statusClass = 'seat-available';
          if (seat.status === 'sold') statusClass = 'seat-sold';
          else if (seat.status === 'blocked') statusClass = 'seat-blocked';

          const isSelected = state.selectedSeats.has(seat.seat_id);
          const selClass = isSelected ? 'seat-selected' : '';

          html += `
            <button type="button" 
                    class="seat-btn ${statusClass} ${selClass}" 
                    data-seat-id="${seat.seat_id}"
                    data-status="${seat.status}"
                    title="Seat ${seat.seat_id} (${seat.status})">
              ${seat.seat_num}
            </button>
          `;
        });

        html += `
            </div>
            <span class="w-6 text-left text-xs font-bold text-gray-500 font-mono">${rowLabel}</span>
          </div>
        `;
      });

      html += `</div>`;
    });

    seatGridContent.innerHTML = html;

    seatGridContent.querySelectorAll('.seat-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const seatId = btn.getAttribute('data-seat-id');
        initAudioContext();

        if (state.selectedSeats.has(seatId)) {
          state.selectedSeats.delete(seatId);
          btn.classList.remove('seat-selected');
        } else {
          state.selectedSeats.add(seatId);
          btn.classList.add('seat-selected');
        }
        renderSelectedSeatsChips();
      });
    });
  }

  function renderSelectedSeatsChips() {
    if (state.selectedSeats.size === 0) {
      selectedSeatsChips.innerHTML = '<span class="text-xs text-gray-500 italic">None selected yet. Click seats in the map above.</span>';
      return;
    }
    let html = '';
    state.selectedSeats.forEach((seatId) => {
      html += `
        <span class="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-700 text-xs font-mono font-bold">
          <span>${seatId}</span>
          <button type="button" class="remove-seat-chip hover:text-red-400 font-bold ml-1" data-seat="${seatId}">✕</button>
        </span>
      `;
    });
    selectedSeatsChips.innerHTML = html;

    selectedSeatsChips.querySelectorAll('.remove-seat-chip').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const sId = btn.getAttribute('data-seat');
        state.selectedSeats.delete(sId);
        const seatBtn = seatGridContent.querySelector(`[data-seat-id="${sId}"]`);
        if (seatBtn) seatBtn.classList.remove('seat-selected');
        renderSelectedSeatsChips();
      });
    });
  }

  // ==========================================
  // 5. Watch Job Management (Create/Poll)
  // ==========================================
  async function createWatchJob(mode) {
    if (!state.selectedMovie) {
      alert('Please select or enter a movie.');
      return;
    }
    const theatreName = (state.selectedTheatre && state.selectedTheatre.theatre_name) || customTheatreInput.value.trim();
    if (!theatreName) {
      alert('Please select or specify an expected theatre name.');
      return;
    }
    const targetDate = targetDateInput.value;
    if (!targetDate) {
      alert('Please select a target date.');
      return;
    }

    const payload = {
      mode: mode,
      city: state.currentCity,
      movie_title: state.selectedMovie.title,
      movie_url: state.selectedMovie.movie_url,
      target_date: targetDate,
      theatre_name: theatreName,
      showtime_str: null,
      watched_seats: null,
      match_rule: 'ANY',
    };

    if (mode === 'SHOW_OPENING') {
      const prefTime = prefTimeFilter.value.trim();
      payload.showtime_str = prefTime || null;
    } else if (mode === 'SEAT_AVAILABILITY') {
      if (state.selectedSeats.size === 0) {
        alert('Please select at least 1 seat from the seat map to watch.');
        return;
      }
      payload.showtime_str = state.selectedShowtime || null;
      payload.watched_seats = Array.from(state.selectedSeats);
      const matchRadio = document.querySelector('input[name="match-rule"]:checked');
      payload.match_rule = matchRadio ? matchRadio.value : 'ANY';
    }

    try {
      const res = await fetch('/api/watches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        initAudioContext();
        await fetchWatchJobs();
        alert(`Watch started successfully! Monitoring ${payload.theatre_name} in background.`);
      } else {
        const err = await res.json();
        alert('Failed to create watch: ' + (err.detail || 'Unknown error'));
      }
    } catch (e) {
      console.error('Error creating watch job:', e);
      alert('Network error while starting watch.');
    }
  }

  async function fetchWatchJobs() {
    try {
      const res = await fetch('/api/watches');
      if (res.ok) {
        state.activeWatches = await res.json();
        renderWatchesList();
        updateStats();
      }
    } catch (e) {
      console.warn('Failed to fetch watch jobs:', e);
    }
  }

  function renderWatchesList() {
    if (!state.activeWatches || state.activeWatches.length === 0) {
      watchesList.innerHTML = `
        <div class="text-center py-10 text-gray-500 text-sm space-y-2">
          <span class="text-4xl block">🎬</span>
          <p>No active watches currently.</p>
          <p class="text-xs text-gray-600">Select a movie and start a watch job on the left panel.</p>
        </div>
      `;
      return;
    }

    let html = '';
    state.activeWatches.forEach((job) => {
      const isMode1 = job.mode === 'SHOW_OPENING';
      const modeBadge = isMode1
        ? '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950 text-blue-400 border border-blue-800">SHOW OPENING</span>'
        : '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-950 text-cyan-400 border border-cyan-800">SEAT WATCH</span>';

      let statusBadge = '';
      if (job.status === 'ACTIVE') {
        statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center space-x-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping inline-block"></span><span>ACTIVE</span></span>';
      } else if (job.status === 'PAUSED') {
        statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-gray-800 text-gray-400 border border-gray-700">PAUSED</span>';
      } else if (job.status === 'TRIGGERED') {
        statusBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800 font-extrabold">🎉 TRIGGERED</span>';
      }

      let seatsHtml = '';
      if (job.watched_seats && job.watched_seats.length > 0) {
        seatsHtml = `
          <div class="mt-2 flex flex-wrap items-center gap-1">
            <span class="text-[11px] text-gray-400">Watched Seats (${job.match_rule}):</span>
            ${job.watched_seats.map(s => `<span class="px-1.5 py-0.5 bg-gray-800 text-cyan-300 rounded text-[10px] font-mono">${s}</span>`).join('')}
          </div>
        `;
      }

      html += `
        <div class="p-3.5 bg-gray-900/80 rounded-xl border border-gray-800 hover:border-gray-700 transition space-y-2">
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="flex items-center space-x-2">
                ${modeBadge}
                ${statusBadge}
              </div>
              <h4 class="text-sm font-bold text-white mt-1">${job.movie_title}</h4>
              <p class="text-xs text-gray-400">
                📍 ${job.theatre_name} &bull; 📅 ${job.target_date} ${job.showtime_str ? '&bull; ⏰ ' + job.showtime_str : ''}
              </p>
            </div>
            
            <div class="flex items-center space-x-1.5">
              ${job.status === 'ACTIVE' 
                ? `<button class="p-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded text-xs transition" title="Pause Watch" onclick="window.toggleWatchStatus(${job.id}, 'PAUSED')">⏸️</button>` 
                : `<button class="p-1.5 bg-emerald-950 hover:bg-emerald-900 text-emerald-300 rounded text-xs transition border border-emerald-700" title="Resume Watch" onclick="window.toggleWatchStatus(${job.id}, 'ACTIVE')">▶️</button>`
              }
              <a href="${job.movie_url}" target="_blank" class="p-1.5 bg-gray-800 hover:bg-gray-700 text-cyan-400 rounded text-xs transition" title="Open on District">↗️</a>
              <button class="p-1.5 bg-gray-800 hover:bg-red-950 hover:text-red-400 text-gray-400 rounded text-xs transition" title="Delete Watch" onclick="window.deleteWatch(${job.id})">🗑️</button>
            </div>
          </div>

          ${seatsHtml}

          <div class="pt-1 border-t border-gray-800/80 flex items-center justify-between text-[11px] text-gray-400">
            <span class="truncate max-w-[280px]" title="${job.last_check_summary || 'Waiting for first check...'}">
              ${job.last_check_summary || '⏳ Waiting for first poll check...'}
            </span>
            <span class="text-gray-500 font-mono text-[10px]">
              ${job.last_checked_at ? 'Checked ' + job.last_checked_at.split(' ')[1] : ''}
            </span>
          </div>
        </div>
      `;
    });

    watchesList.innerHTML = html;
  }

  function updateStats() {
    const activeCount = state.activeWatches.filter(w => w.status === 'ACTIVE').length;
    statActiveWatches.textContent = activeCount;
  }

  window.toggleWatchStatus = async function (id, targetStatus) {
    try {
      const res = await fetch(`/api/watches/${id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: targetStatus }),
      });
      if (res.ok) {
        await fetchWatchJobs();
      }
    } catch (e) {
      console.error('Error updating watch status:', e);
    }
  };

  window.deleteWatch = async function (id) {
    if (!confirm('Are you sure you want to remove this watch?')) return;
    try {
      const res = await fetch(`/api/watches/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await fetchWatchJobs();
      }
    } catch (e) {
      console.error('Error deleting watch:', e);
    }
  };

  // ==========================================
  // 6. Alert Notification Polling & Sound Cue
  // ==========================================
  async function pollAlerts() {
    try {
      const res = await fetch('/api/alerts/unacknowledged');
      if (res.ok) {
        const alerts = await res.json();
        if (alerts && alerts.length > 0) {
          handleIncomingAlert(alerts[0]);
          if (silenceAlarmBtn) silenceAlarmBtn.classList.remove('hidden');
        } else {
          if (!currentActiveAlert && silenceAlarmBtn) {
            checkLocalSoundStatus();
          }
        }
      }
    } catch (e) {}
  }

  async function checkLocalSoundStatus() {
    try {
      const res = await fetch('/api/alerts/sound-status');
      if (res.ok) {
        const data = await res.json();
        if (data.ringing) {
          if (silenceAlarmBtn) silenceAlarmBtn.classList.remove('hidden');
        } else {
          if (silenceAlarmBtn) silenceAlarmBtn.classList.add('hidden');
        }
      }
    } catch (e) {}
  }

  async function silenceLocalSound() {
    try {
      await fetch('/api/alerts/silence-sound', { method: 'POST' });
    } catch (e) {}
    if (silenceAlarmBtn) silenceAlarmBtn.classList.add('hidden');
  }

  async function pollRecentAlertHistory() {
    try {
      const res = await fetch('/api/alerts/recent');
      if (res.ok) {
        const alerts = await res.json();
        statAlertsFired.textContent = alerts.length;
        if (alerts.length > 0) {
          let html = '';
          alerts.slice(0, 10).forEach((a) => {
            html += `
              <div class="p-2 bg-gray-900 rounded border border-gray-800 flex items-start justify-between">
                <div>
                  <span class="font-bold text-cyan-400">[${a.event_type}]</span>
                  <span class="text-gray-200 ml-1 font-semibold">${a.title}</span>
                  <p class="text-gray-400 mt-0.5">${a.message}</p>
                </div>
                <span class="text-gray-500 font-mono text-[10px] whitespace-nowrap ml-2">${a.created_at.split(' ')[1] || ''}</span>
              </div>
            `;
          });
          alertHistoryList.innerHTML = html;
        }
      }
    } catch (e) {}
  }

  function handleIncomingAlert(alertItem) {
    if (currentActiveAlert && currentActiveAlert.id === alertItem.id) {
      return;
    }
    currentActiveAlert = alertItem;

    if (silenceAlarmBtn) silenceAlarmBtn.classList.remove('hidden');

    playAlertSound(state.settings.sound_tone, state.settings.sound_volume);

    if ('Notification' in window && Notification.permission === 'granted') {
      try {
        const n = new Notification(alertItem.title, {
          body: alertItem.message,
          icon: '/static/favicon.ico',
        });
        n.onclick = function () {
          window.focus();
        };
      } catch (ne) {}
    }

    modalAlertTitle.textContent = alertItem.title;
    modalAlertType.textContent = alertItem.event_type;
    modalAlertMessage.textContent = alertItem.message;
    alertModal.classList.remove('hidden');
    alertModal.classList.add('flex');

    const matchingWatch = state.activeWatches.find(w => w.id === alertItem.watch_job_id);
    modalBookBtn.href = matchingWatch ? matchingWatch.movie_url : 'https://www.district.in/movies/';
  }

  async function acknowledgeCurrentAlert() {
    silenceLocalSound();
    if (!currentActiveAlert) {
      alertModal.classList.add('hidden');
      alertModal.classList.remove('flex');
      return;
    }
    try {
      await fetch(`/api/alerts/${currentActiveAlert.id}/ack`, { method: 'POST' });
    } catch (e) {}
    alertModal.classList.add('hidden');
    alertModal.classList.remove('flex');
    currentActiveAlert = null;
    await fetchWatchJobs();
    await pollRecentAlertHistory();
  }

  // ==========================================
  // 7. Event Listeners & Initialization
  // ==========================================
  function setupEventListeners() {
    document.body.addEventListener('click', initAudioContext, { once: false });

    armAudioBtn.addEventListener('click', () => {
      initAudioContext();
    });

    soundToggleBtn.addEventListener('click', () => {
      initAudioContext();
      const newState = !state.settings.sound_enabled;
      saveSettings({ sound_enabled: newState });
    });

    soundToneSelect.addEventListener('change', (e) => {
      initAudioContext();
      const newTone = e.target.value;
      saveSettings({ sound_tone: newTone });
      playAlertSound(newTone, state.settings.sound_volume);
    });

    soundVolumeSlider.addEventListener('input', (e) => {
      const vol = parseFloat(e.target.value);
      saveSettings({ sound_volume: vol });
    });

    if (selectAllSoldBtn) {
      selectAllSoldBtn.addEventListener('click', () => {
        initAudioContext();
        const soldButtons = seatGridContent.querySelectorAll('.seat-btn.seat-sold');
        if (soldButtons.length === 0) {
          alert('No booked or sold seats found on this seating chart.');
          return;
        }
        soldButtons.forEach((btn) => {
          const seatId = btn.getAttribute('data-seat-id');
          state.selectedSeats.add(seatId);
          btn.classList.add('seat-selected');
        });
        renderSelectedSeatsChips();
        const anyRadio = document.querySelector('input[name="match-rule"][value="ANY"]');
        if (anyRadio) anyRadio.checked = true;
      });
    }

    citySelect.addEventListener('change', (e) => {
      const city = e.target.value;
      saveSettings({ last_selected_city: city });
      fetchMovies(city);
    });

    movieSelect.addEventListener('change', (e) => {
      const idx = e.target.value;
      if (idx !== '') {
        state.selectedMovie = state.movies[parseInt(idx, 10)];
        fetchTheatresAndShows();
      } else {
        state.selectedMovie = null;
      }
    });

    loadDirectMovieBtn.addEventListener('click', () => {
      const url = directMovieUrl.value.trim();
      const title = directMovieTitle.value.trim() || 'Custom District Movie';
      if (!url) {
        alert('Please enter a valid movie URL');
        return;
      }
      state.selectedMovie = {
        title: title,
        movie_url: url,
        languages: [],
        formats: ['2D'],
        is_upcoming: false,
      };
      alert(`Selected: ${title} (${url})`);
      fetchTheatresAndShows();
    });

    targetDateInput.addEventListener('change', () => {
      fetchTheatresAndShows();
    });

    refreshShowsBtn.addEventListener('click', () => {
      fetchTheatresAndShows();
    });

    theatreSelect.addEventListener('change', (e) => {
      const idx = e.target.value;
      if (idx !== '') {
        state.selectedTheatre = state.theatres[parseInt(idx, 10)];
        renderShowtimePills(state.selectedTheatre);
      } else {
        state.selectedTheatre = null;
      }
    });

    tabMode1.addEventListener('click', () => {
      state.currentMode = 'SHOW_OPENING';
      tabMode1.className = 'py-2 px-3 rounded-md text-xs font-bold transition flex items-center justify-center space-x-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white shadow';
      tabMode2.className = 'py-2 px-3 rounded-md text-xs font-bold transition flex items-center justify-center space-x-2 bg-transparent text-gray-400 hover:text-gray-200';
      mode1Panel.classList.remove('hidden');
      mode2Panel.classList.add('hidden');
    });

    tabMode2.addEventListener('click', () => {
      state.currentMode = 'SEAT_AVAILABILITY';
      tabMode2.className = 'py-2 px-3 rounded-md text-xs font-bold transition flex items-center justify-center space-x-2 bg-gradient-to-r from-cyan-600 to-sky-600 text-white shadow';
      tabMode1.className = 'py-2 px-3 rounded-md text-xs font-bold transition flex items-center justify-center space-x-2 bg-transparent text-gray-400 hover:text-gray-200';
      mode2Panel.classList.remove('hidden');
      mode1Panel.classList.add('hidden');
    });

    startMode1Btn.addEventListener('click', () => {
      createWatchJob('SHOW_OPENING');
    });

    loadSeatMapBtn.addEventListener('click', () => {
      loadSeatMap();
    });

    startMode2Btn.addEventListener('click', () => {
      createWatchJob('SEAT_AVAILABILITY');
    });

    refreshWatchesBtn.addEventListener('click', () => {
      fetchWatchJobs();
    });

    if (silenceAlarmBtn) {
      silenceAlarmBtn.addEventListener('click', async () => {
        await silenceLocalSound();
      });
    }

    modalBookBtn.addEventListener('click', () => {
      silenceLocalSound();
    });

    modalAckBtn.addEventListener('click', () => {
      acknowledgeCurrentAlert();
    });

    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }

  function initDefaultDate() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    targetDateInput.value = `${yyyy}-${mm}-${dd}`;
  }

  async function boot() {
    initDefaultDate();
    setupEventListeners();
    await loadSettings();
    if (state.settings.last_selected_city) {
      citySelect.value = state.settings.last_selected_city;
      state.currentCity = state.settings.last_selected_city;
    }
    await fetchMovies(state.currentCity);
    await fetchWatchJobs();
    await pollRecentAlertHistory();

    setInterval(pollAlerts, 3000);
    setInterval(fetchWatchJobs, 6000);
    setInterval(pollRecentAlertHistory, 10000);
    setInterval(checkAudioState, 5000);
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
