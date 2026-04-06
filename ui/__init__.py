def __init__(self):
    """Initialize main window"""
    super().__init__()
    
    # Directories
    self.script_dir = os.path.dirname(os.path.abspath(__file__))
    self.log_directory = os.path.join(self.script_dir, "..", "logs")
    self.report_directory = os.path.join(self.script_dir, "..", "reports")
    os.makedirs(self.log_directory, exist_ok=True)
    os.makedirs(self.report_directory, exist_ok=True)
    
    # Hardware
    self.daq = SimpleDAQController()
    
    # UUTs and testing state
    self.uuts = []
    self.current_test_executor = None
    self.current_uut_index = -1
    self.batch_start_datetime = None
    self.batch_end_time = None
    self.testing_active = False
    self.current_statistics = None
    
    # Test configuration
    self.test_config = {
        'ibit_timeout': 300.0,
        'phase_timeout': 90.0,
        'arm_timeout': 60.0,
        'max_arm_iterations': 20,
        'skip_arm_for_ibit': False
    }
    
    # Initialize timers BEFORE init_ui (which calls _connect_signals)
    self.daq_health_timer = QTimer()
    self.elapsed_timer = QTimer()
    
    # Build UI
    self.init_ui()
    
    # Configure timers AFTER UI is built
    self.daq_health_timer.timeout.connect(self.check_daq_health)
    self.daq_health_timer.start(60000)  # Check every minute
    
    # Load settings after UI is built
    QTimer.singleShot(100, self.load_settings)
    QTimer.singleShot(500, self.detect_daq_devices)