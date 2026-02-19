# Sprint Plan - Real-time Features & Testing

**Sprint Duration**: 2 weeks (Feb 19 - Mar 4, 2026)  
**Sprint Goal**: Implement real-time live scores, comprehensive testing, and CI/CD pipeline

---

## 📋 Sprint Backlog

### Week 1: Real-time Features & Core Testing

#### Day 1 (Feb 19) - Testing Infrastructure ✅
- [x] Create comprehensive test suite
  - [x] API endpoint tests
  - [x] Data indexer tests
  - [x] Scheduler tests
  - [x] Stats service tests
- [x] Setup GitHub Actions CI/CD
- [x] Configure test coverage reporting
- [x] Document testing approach

**Deliverables**: 
- Complete test suite with >70% coverage
- Automated CI/CD pipeline
- Testing documentation

---

#### Day 2-3 (Feb 20-21) - WebSocket Live Scores
- [ ] Backend: Create WebSocket endpoint
  - [ ] `/api/v1/ws/live-scores` endpoint
  - [ ] Background task to poll Swiss Unihockey API
  - [ ] Filter and format live game data
  - [ ] Handle WebSocket connections/disconnections
- [ ] Database: Add game status tracking
  - [ ] Add `status` field to Games table (scheduled/live/finished)
  - [ ] Add `live_home_score` and `live_away_score` fields
  - [ ] Create indexer job to update live game status
- [ ] Frontend: Live scores page
  - [ ] Create `/de/live` page
  - [ ] WebSocket client connection
  - [ ] Live score cards with real-time updates
  - [ ] Auto-refresh every 10 seconds
- [ ] Testing
  - [ ] Unit tests for WebSocket endpoint
  - [ ] Integration tests with mock data
  - [ ] Load testing with multiple connections

**Files to Create**:
```
backend/app/api/v1/endpoints/live.py
backend/app/services/live_scores_service.py
backend/tests/test_live_scores.py
backend/templates/live.html
```

**Success Criteria**:
- WebSocket endpoint functional and stable
- Live scores update automatically
- Handles 100+ concurrent connections
- Tests pass with >80% coverage

---

#### Day 4-5 (Feb 22-23) - Push Notifications
- [ ] Backend: Web Push API integration
  - [ ] Generate VAPID keys
  - [ ] Create subscription endpoint `/api/v1/subscribe`
  - [ ] Store subscriptions in database
  - [ ] Create notification service
  - [ ] Trigger notifications on events (goals, game start)
- [ ] Database: Subscription management
  - [ ] Add `push_subscriptions` table
  - [ ] Add `user_notifications_preferences` table
- [ ] Frontend: Notification UI
  - [ ] Request notification permission
  - [ ] Subscribe/unsubscribe functionality
  - [ ] Notification preferences page
  - [ ] Test notification button
- [ ] Service Worker: Handle push events
- [ ] Testing
  - [ ] Test subscription flow
  - [ ] Test notification delivery
  - [ ] Test unsubscribe

**Files to Create**:
```
backend/app/api/v1/endpoints/notifications.py
backend/app/services/push_notification_service.py
backend/app/models/db_models.py (add PushSubscription model)
backend/tests/test_notifications.py
backend/templates/notifications.html
backend/static/js/notifications.js
```

**Success Criteria**:
- Users can subscribe to notifications
- Notifications sent on goal events
- Preferences are saved and respected
- Tests pass with >75% coverage

---

### Week 2: Analytics & Polish

#### Day 6-8 (Feb 24-26) - Advanced Analytics
- [ ] Player Comparison Tool
  - [ ] Backend: Comparison endpoint `/api/v1/players/compare`
  - [ ] Frontend: Comparison page `/de/compare`
  - [ ] Select 2-4 players for side-by-side comparison
  - [ ] Display stats, charts, radar charts
- [ ] Team Performance Trends
  - [ ] Backend: Calculate win/loss streaks, goal trends
  - [ ] Frontend: Team trends page
  - [ ] Line charts for goals, points over time
- [ ] League Analytics Dashboard
  - [ ] Top performers by position
  - [ ] Team comparisons
  - [ ] League-wide statistics
- [ ] Testing
  - [ ] Test comparison calculations
  - [ ] Test chart data generation
  - [ ] Performance tests for large datasets

**Files to Create**:
```
backend/app/api/v1/endpoints/analytics.py
backend/app/services/analytics_service.py
backend/tests/test_analytics.py
backend/templates/compare.html
backend/templates/analytics.html
backend/static/js/charts.js (enhance existing)
```

**Success Criteria**:
- Comparison tool works for 2-4 players
- Charts render correctly
- Performance <500ms for analytics queries
- Tests pass with >70% coverage

---

#### Day 9-10 (Feb 27-28) - Performance Optimization
- [ ] Database Optimization
  - [ ] Add missing indexes
  - [ ] Optimize slow queries
  - [ ] Add query result caching
- [ ] Redis Integration (Optional)
  - [ ] Setup Redis server
  - [ ] Implement Redis caching layer
  - [ ] Cache hot data (standings, top scorers)
- [ ] Frontend Optimization
  - [ ] Implement lazy loading for images
  - [ ] Add virtual scrolling for large lists
  - [ ] Optimize bundle size
  - [ ] Add performance monitoring
- [ ] Testing
  - [ ] Load testing with Apache Bench
  - [ ] Lighthouse performance audit
  - [ ] Test caching effectiveness

**Files to Update**:
```
backend/app/services/cache_service.py (new)
backend/app/config.py (add Redis config)
backend/requirements.txt (add redis package)
backend/static/js/lazy-loading.js (enhance)
```

**Performance Targets**:
- API response time <200ms (p95)
- Page load time <2s
- Lighthouse score >90
- Cache hit rate >80%

---

#### Day 11-12 (Mar 1-2) - Bug Fixes & Documentation
- [ ] Bug Triage
  - [ ] Review and fix reported issues
  - [ ] Test edge cases
  - [ ] Fix UI/UX issues
- [ ] Documentation
  - [ ] Update API documentation
  - [ ] Write user guide
  - [ ] Update README with new features
  - [ ] Create developer setup guide
- [ ] Code Review
  - [ ] Review all new code
  - [ ] Refactor as needed
  - [ ] Ensure consistent style
- [ ] Final Testing
  - [ ] Run full test suite
  - [ ] Manual testing of all features
  - [ ] Cross-browser testing
  - [ ] Mobile device testing

**Files to Create/Update**:
```
docs/API_DOCUMENTATION.md
docs/USER_GUIDE.md
docs/DEVELOPER_SETUP.md
README.md
CHANGELOG.md
```

---

#### Day 13-14 (Mar 3-4) - Sprint Review & Retrospective
- [ ] Sprint Review
  - [ ] Demo all new features
  - [ ] Collect feedback
  - [ ] Update documentation
- [ ] Code cleanup
  - [ ] Remove debug code
  - [ ] Update comments
  - [ ] Final lint and format
- [ ] Deployment
  - [ ] Deploy to staging
  - [ ] Run smoke tests
  - [ ] Deploy to production
- [ ] Sprint Retrospective
  - [ ] What went well?
  - [ ] What could be improved?
  - [ ] Action items for next sprint

---

## 📊 Definition of Done

A task is considered "Done" when:
- ✅ Code is written and reviewed
- ✅ Unit tests written and passing
- ✅ Integration tests passing
- ✅ Documentation updated
- ✅ No critical bugs
- ✅ Lighthouse score >85
- ✅ Code coverage >70%
- ✅ Committed and pushed to main
- ✅ Deployed to staging
- ✅ Manual testing completed

---

## 🎯 Sprint Success Metrics

### Technical Metrics
- [ ] Test coverage: >70%
- [ ] All tests passing
- [ ] CI/CD pipeline green
- [ ] API response time: <200ms (p95)
- [ ] Page load time: <2s
- [ ] Lighthouse score: >90
- [ ] Zero critical bugs

### Feature Metrics
- [ ] Live scores functional
- [ ] Push notifications working
- [ ] Analytics page live
- [ ] Performance optimized
- [ ] Documentation complete

### Quality Metrics
- [ ] Code review completed
- [ ] Security review passed
- [ ] Accessibility tested
- [ ] Cross-browser tested
- [ ] Mobile tested on real devices

---

## 🚧 Risks & Mitigation

### Risk 1: WebSocket Complexity
**Impact**: High  
**Probability**: Medium  
**Mitigation**: 
- Start with simple implementation
- Use existing libraries (websockets)
- Test with mock data first
- Have fallback to polling if needed

### Risk 2: Push Notification Browser Support
**Impact**: Medium  
**Probability**: High  
**Mitigation**:
- Test on multiple browsers
- Provide graceful degradation
- Document browser requirements
- Consider using OneSignal as backup

### Risk 3: Performance Degradation
**Impact**: High  
**Probability**: Low  
**Mitigation**:
- Monitor performance continuously
- Add caching aggressively
- Optimize database queries
- Load testing before deployment

### Risk 4: Time Constraints
**Impact**: Medium  
**Probability**: Medium  
**Mitigation**:
- Focus on MVP features first
- Cut scope if needed (analytics can wait)
- Extend sprint if critical features incomplete
- Maintain daily progress tracking

---

## 📅 Daily Standups

Each day at 9:00 AM, review:
1. What did I complete yesterday?
2. What will I work on today?
3. Any blockers or challenges?

---

## 🎉 Sprint Deliverables

At the end of this sprint, we will have:
1. ✅ Comprehensive test suite with CI/CD
2. ✅ Live scores with WebSocket
3. ✅ Push notifications
4. ✅ Analytics dashboard
5. ✅ Performance optimizations
6. ✅ Complete documentation
7. ✅ Production-ready code

**Next Sprint**: User accounts and personalization

---

**Created**: February 19, 2026  
**Sprint Master**: Development Team  
**Stakeholders**: Users, Swiss Unihockey Community
