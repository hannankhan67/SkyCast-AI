describe('Analyst Telemetry Dashboard', () => {
  beforeEach(() => {
    // Intercept initial live-data endpoint calls with mock telemetry
    cy.intercept('GET', '/api/telemetry/live-data', {
      statusCode: 200,
      body: {
        total_requests: 1420,
        avg_latency: 42,
        active_keys: 18,
        success_rate: 96.4,
        is_simulated: false,
        chart_labels: ['12:00', '12:05', '12:10', '12:15'],
        chart_requests: [120, 150, 180, 210],
        chart_latencies: [45, 40, 42, 38]
      }
    }).as('getTelemetry');

    // Freeze timer to precisely control setInterval testing
    cy.clock();

    // Visit dashboard route
    cy.visit('/dashboard');
  });

  context('Keyboard Shortcuts Modal', () => {
    it('opens modal when pressing "?" and closes on "Esc"', () => {
      cy.get('#shortcutsModal').should('have.class', 'opacity-0');

      cy.get('body').type('?');

      cy.get('#shortcutsModal').should('not.have.class', 'opacity-0');
      cy.get('#shortcutsModalCard')
        .should('be.visible')
        .and('contain.text', 'Analyst Keyboard Shortcuts');

      cy.get('body').type('{esc}');

      cy.get('#shortcutsModal').should('have.class', 'opacity-0');
    });

    it('opens modal via button click and closes via backdrop click', () => {
      cy.contains('button', 'Shortcuts').click();
      cy.get('#shortcutsModal').should('not.have.class', 'opacity-0');

      cy.get('#shortcutsModal > .absolute.inset-0').click({ force: true });
      cy.get('#shortcutsModal').should('have.class', 'opacity-0');
    });

    it('ignores shortcut keys when typing inside input fields', () => {
      cy.get('body').then(($body) => {
        if ($body.find('input[type="text"]').length > 0) {
          cy.get('input[type="text"]').first().focus().type('Karachi?');
          cy.get('#shortcutsModal').should('have.class', 'opacity-0');
        }
      });
    });
  });

  context('Live Telemetry Polling', () => {
    it('polls new data every 5 seconds', () => {
      cy.tick(5000);
      cy.wait('@getTelemetry');

      cy.tick(5000);
      cy.wait('@getTelemetry');

      cy.get('#kpiTotalRequests').should('contain.text', '1,420');
      cy.get('#kpiAvgLatency').should('contain.text', '42 ms');
    });

    it('pauses and resumes polling via button and Alt + P key', () => {
      cy.get('#pollingToggleBtn').click();
      cy.get('#pollingBtnText').should('contain.text', 'Resume Polling');

      cy.tick(10000);
      cy.get('@getTelemetry.all').should('have.length', 0);

      cy.get('body').type('{alt}p');
      cy.get('#pollingBtnText').should('contain.text', 'Pause Polling');

      cy.tick(5000);
      cy.wait('@getTelemetry');
    });
  });
});
