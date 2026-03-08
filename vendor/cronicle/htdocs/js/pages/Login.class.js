Class.subclass( Page.Base, "Page.Login", {	
	
	onInit: function() {
		// called once at page load
		// var html = 'Now is the time (LOGIN)';
		// this.div.html( html );
	},
	
	onActivate: function(args) {
		// page activation
		if (app.user) {
			// user already logged in
			setTimeout( function() { Nav.go(app.navAfterLogin || config.DefaultPage) }, 1 );
			return true;
		}
		else if (args.u && args.h) {
			this.showPasswordResetForm(args);
			return true;
		}
		else if (args.create) {
			this.showCreateAccountForm();
			return true;
		}
		else if (args.recover) {
			this.showRecoverPasswordForm();
			return true;
		}
		
		app.setWindowTitle(_t('login.login'));
		app.showTabBar(false);
		
		this.div.css({ 'padding-top':'75px', 'padding-bottom':'75px' });
		var html = '';
		
		html += '<div class="inline_dialog_container">';
			html += '<div class="dialog_title shade-light">' + _t('login.user_login') + '</div>';
			html += '<div class="dialog_content">';
				html += '<center><table style="margin:0px;">';
					html += '<tr>';
						html += '<td align="right" class="table_label">' + _t('login.username') + '</td>';
						html += '<td align="left" class="table_value"><div><input type="text" name="username" id="fe_login_username" size="30" spellcheck="false" value="'+(app.getPref('username') || '')+'"/></div></td>';
					html += '</tr>';
					html += '<tr><td colspan="2"><div class="table_spacer"></div></td></tr>';
					html += '<tr>';
						html += '<td align="right" class="table_label">' + _t('login.password') + '</td>';
						html += '<td align="left" class="table_value"><div><input type="' + app.get_password_type() + '" name="password" id="fe_login_password" size="30" spellcheck="false" value=""/>' + app.get_password_toggle_html() + '</div></td>';
					html += '</tr>';
					html += '<tr><td colspan="2"><div class="table_spacer"></div></td></tr>';
				html += '</table></center>';
			html += '</div>';
			
			html += '<div class="dialog_buttons"><center><table><tr>';
				if (config.free_accounts) {
					html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().navCreateAccount()">' + _t('login.create_account') + '</div></td>';
					html += '<td width="20">&nbsp;</td>';
				}
				html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().navPasswordRecovery()">' + _t('login.forgot_password') + '</div></td>';
				html += '<td width="20">&nbsp;</td>';
				html += '<td><div class="button" style="width:120px;" onMouseUp="$P().doLogin()"><i class="fa fa-sign-in">&nbsp;&nbsp;</i>' + _t('login.btn_login') + '</div></td>';
				if (config.oauth) {
					html += '<td width="20">&nbsp;</td>';
					html += '<td><div class="button" style="width:120px;" onMouseUp="$P().doOauth()"><i class="fa fa-sign-in">&nbsp;&nbsp;</i>' + _t('login.btn_sso') + '</div></td>';
				}
			html += '</tr></table></center></div>';
		html += '</div>';
		
		// html += '<input type="submit" value="Login" style="position:absolute; left:-9999px; top:0px;">';
		html += '</form>';
		this.div.html( html );
		
		setTimeout( function() {
			$( app.getPref('username') ? '#fe_login_password' : '#fe_login_username' ).focus();
			
			 $('#fe_login_username, #fe_login_password').keypress( function(event) {
				if (event.keyCode == '13') { // enter key
					event.preventDefault();
					$P().doLogin();
				}
			} ); 
			
		}, 1 );

		return true;
	},

	doOauth: function() {

		if(localStorage.session_id) { 
			// user might be logged aleready in differnt tab, then just refresh the page
			Nav.go(app.navAfterLogin || config.DefaultPage)
		}
		else {
			// redirect to oauth login page
			let orig_location = encodeURIComponent(app.navAfterLogin || config.DefaultPage);
			window.location.href = app.config.base_api_uri + `/user/oauth?orig_location=${orig_location}`;	
		}

	},

	
	 doLogin: function() {
		// attempt to log user in
		var username = $('#fe_login_username').val().toLowerCase();
		var password = $('#fe_login_password').val();
		
		if (username && password) {
			app.showProgress(1.0, _t('login.logging_in'));
			
			app.api.post( 'user/login', {
				username: username,
				password: password
			}, 
			function(resp, tx) {
				Debug.trace("User Login: " + username + ": " + resp.session_id);
				
				app.hideProgress();
				app.doUserLogin( resp );
				if(document.referrer ) window.location.href = document.referrer
				else Nav.go( app.navAfterLogin || config.DefaultPage );
			} ); // post
		}
	}, 
	
	cancel: function() {
		// return to login page
		app.clearError();
		Nav.go('Login', true);
	},
	
	navCreateAccount: function() {
		// nav to create account form
		app.clearError();
		Nav.go('Login?create=1', true);
	},
	
	showCreateAccountForm: function() {
		// allow user to create a new account
		app.setWindowTitle(_t('login.create_account'));
		app.showTabBar(false);
		
		this.div.css({ 'padding-top':'75px', 'padding-bottom':'75px' });
		var html = '';
		
		html += '<div class="inline_dialog_container">';
			html += '<div class="dialog_title shade-light">' + _t('login.create_account') + '</div>';
			html += '<div class="dialog_content">';
				html += '<center><table style="margin:0px;">';
				
				html += get_form_table_row( _t('login.username'), 
					'<table cellspacing="0" cellpadding="0"><tr>' + 
						'<td><input type="text" id="fe_ca_username" size="20" style="font-size:14px;" value="" spellcheck="false" onChange="$P().checkUserExists(\'ca\')"/></td>' + 
						'<td><div id="d_ca_valid" style="margin-left:5px; font-weight:bold;"></div></td>' + 
					'</tr></table>'
				);
				
				html += get_form_table_caption(_t('login.choose_a_unique_alphanumeric_username_fo')) + 
				get_form_table_spacer() + 
				get_form_table_row(_t('login.password'), '<input type="' + app.get_password_type() + '" id="fe_ca_password" size="30" value="" spellcheck="false"/>' + app.get_password_toggle_html()) + 
				get_form_table_caption(_t('login.enter_a_secure_password_that_you_will_no')) + 
				get_form_table_spacer() + 
				get_form_table_row(_t('login.full_name'), '<input type="text" id="fe_ca_fullname" size="30" value="" spellcheck="false"/>') + 
				get_form_table_caption(_t('login.this_is_used_for_display_purposes_only')) + 
				get_form_table_spacer() + 
				get_form_table_row(_t('login.email_address'), '<input type="text" id="fe_ca_email" size="30" value="" spellcheck="false"/>') + 
				get_form_table_caption(_t('login.this_is_used_only_to_recover_your_passwo'));
					
				html += '</table></center>';
			html += '</div>';
			
			html += '<div class="dialog_buttons"><center><table><tr>';
				html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().cancel()">' + _t('login.cancel') + '</div></td>';
				html += '<td width="50">&nbsp;</td>';
				html += '<td><div class="button" style="width:120px;" onMouseUp="$P().doCreateAccount()"><i class="fa fa-user-plus">&nbsp;&nbsp;</i>' + _t('login.create') + '</div></td>';
			html += '</tr></table></center></div>';
		html += '</div>';
		
		this.div.html( html );
		
		setTimeout( function() {
			$( '#fe_ca_username' ).focus();
			app.password_strengthify( '#fe_ca_password' );
		}, 1 );
	},
	
	doCreateAccount: function(force) {
		// actually create account
		app.clearError();
		
		var username = trim($('#fe_ca_username').val().toLowerCase());
		var email = trim($('#fe_ca_email').val());
		var full_name = trim($('#fe_ca_fullname').val());
		var password = trim($('#fe_ca_password').val());
		
		if (!username.length) {
			return app.badField('#fe_ca_username', _t('login.please_enter_a_username_for_your_account'));
		}
		if (!username.match(/^[\w\.\-]+@?[\w\.\-]+$/)) {
			return app.badField('#fe_ca_username', _t('login.please_make_sure_your_username_contains_'));
		}
		if (!email.length) {
			return app.badField('#fe_ca_email', _t('login.please_enter_an_email_address_where_you_'));
		}
		if (!email.match(/^\S+\@\S+$/)) {
			return app.badField('#fe_ca_email', _t('login.the_email_address_you_entered_does_not_a'));
		}
		if (!full_name.length) {
			return app.badField('#fe_ca_fullname', _t('login.please_enter_your_first_and_last_names_t'));
		}
		if (!password.length) {
			return app.badField('#fe_ca_password', _t('login.please_enter_a_secure_password_to_protec'));
		}
		if (!force && (app.last_password_strength.score < 3)) {
			app.confirm( '<span style="color:red">Insecure Password Warning</span>', app.get_password_warning(), "Proceed", function(result) {
				if (result) $P().doCreateAccount('force');
			} );
			return;
		} // insecure password
		
		Dialog.hide();
		app.showProgress( 1.0, _t('login.creating_account') );
		
		app.api.post( 'user/create', {
			username: username,
			email: email,
			password: password,
			full_name: full_name
		}, 
		function(resp, tx) {
			app.hideProgress();
			app.showMessage('success', _t('login.account_created_successfully'));
			
			app.setPref('username', username);
			Nav.go( 'Login', true );
		} ); // api.post
	},
	
	navPasswordRecovery: function() {
		// nav to recover password form
		app.clearError();
		Nav.go('Login?recover=1', true);
	},
	
	showRecoverPasswordForm: function() {
		// allow user to create a new account
		app.setWindowTitle(_t('login.forgot_password'));
		app.showTabBar(false);
		
		this.div.css({ 'padding-top':'75px', 'padding-bottom':'75px' });
		var html = '';
		
		html += '<div class="inline_dialog_container">';
			html += '<div class="dialog_title shade-light">' + _t('login.forgot_password') + '</div>';
			html += '<div class="dialog_content">';
				html += '<center><table style="margin:0px;">';
				
				html += get_form_table_row(_t('login.username'), '<input type="text" id="fe_pr_username" size="30" value="" spellcheck="false"/>') + 
				get_form_table_spacer() + 
				get_form_table_row(_t('login.email_address'), '<input type="text" id="fe_pr_email" size="30" value="" spellcheck="false"/>');
				
				html += '</table></center>';
				
				html += '<div class="caption" style="margin-top:15px;">' + _t('login.please_enter_an_email_address_where_you_') + '</div>';
				
			html += '</div>';
			
			html += '<div class="dialog_buttons"><center><table><tr>';
				html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().cancel()">' + _t('login.cancel') + '</div></td>';
				html += '<td width="50">&nbsp;</td>';
				html += '<td><div class="button" style="width:120px;" onMouseUp="$P().doSendRecoveryEmail()"><i class="fa fa-envelope-o">&nbsp;&nbsp;</i>' + _t('login.send_email') + '</div></td>';
			html += '</tr></table></center></div>';
		html += '</div>';
		
		this.div.html( html );
		
		setTimeout( function() { 
			$('#fe_pr_username, #fe_pr_email').keypress( function(event) {
				if (event.keyCode == '13') { // enter key
					event.preventDefault();
					$P().doSendEmail();
				}
			} );
			$( '#fe_pr_username' ).focus();
		}, 1 );
	},
	
	doSendRecoveryEmail: function() {
		// send password recovery e-mail
		app.clearError();
		
		var username = trim($('#fe_pr_username').val()).toLowerCase();
		var email = trim($('#fe_pr_email').val());
		
		if (username.match(/^[\w.-]+$/)) {
			if (email.match(/.+\@.+/)) {
				Dialog.hide();
				app.showProgress( 1.0, _t('login.sending_email') );
				app.api.post( 'user/forgot_password', {
					username: username,
					email: email
				}, 
				function(resp, tx) {
					app.hideProgress();
					app.showMessage('success', _t('login.password_reset_instructions_sent_success'));
					Nav.go('Login', true);
				} ); // api.post
			} // good address
			else app.badField('#fe_pr_email', _t('login.the_email_address_you_entered_does_not_a'));
		} // good username
		else app.badField('#fe_pr_username', _t('login.the_username_you_entered_does_not_appear'));
	},
	
	showPasswordResetForm: function(args) {
		// show password reset form
		this.recoveryKey = args.h;
		
		app.setWindowTitle(_t('login.reset_password'));
		app.showTabBar(false);
		
		this.div.css({ 'padding-top':'75px', 'padding-bottom':'75px' });
		var html = '';
		
		html += '<div class="inline_dialog_container">';
			html += '<div class="dialog_title shade-light">' + _t('login.reset_password') + '</div>';
			html += '<div class="dialog_content">';
				html += '<center><table style="margin:0px;">';
					html += '<tr>';
						html += '<td align="right" class="table_label">' + _t('login.username') + '</td>';
						html += '<td align="left" class="table_value"><div><input type="text" name="username" id="fe_reset_username" size="30" spellcheck="false" value="' + encode_attrib_entities(args.u) + '" disabled="disabled"/></div></td>';
					html += '</tr>';
					html += '<tr><td colspan="2"><div class="table_spacer"></div></td></tr>';
					html += '<tr>';
						html += '<td align="right" class="table_label">' + _t('login.reset_password') + '</td>';
						html += '<td align="left" class="table_value"><div><input type="' + app.get_password_type() + '" name="password" id="fe_reset_password" size="30" spellcheck="false" value=""/>' + app.get_password_toggle_html() + '</div></td>';
					html += '</tr>';
					html += '<tr><td colspan="2"><div class="table_spacer"></div></td></tr>';
				html += '</table></center>';
			html += '</div>';
			
			html += '<div class="dialog_buttons"><center><table><tr>';
				html += '<td><div class="button" style="width:130px;" onMouseUp="$P().doResetPassword()"><i class="fa fa-key">&nbsp;&nbsp;</i>' + _t('login.reset_password') + '</div></td>';
			html += '</tr></table></center></div>';
		html += '</div>';
		
		this.div.html( html );
		
		setTimeout( function() {
			$( '#fe_reset_password' ).focus();
			$('#fe_reset_password').keypress( function(event) {
				if (event.keyCode == '13') { // enter key
					event.preventDefault();
					$P().doResetPassword();
				}
			} );
			app.password_strengthify( '#fe_reset_password' );
		}, 1 );
	},
	
	doResetPassword: function(force) {
		// reset password now
		var username = $('#fe_reset_username').val().toLowerCase();
		var new_password = $('#fe_reset_password').val();
		var recovery_key = this.recoveryKey;
		
		if (username && new_password) {
			if (!force && (app.last_password_strength.score < 3)) {
				app.confirm( '<span style="color:red">Insecure Password Warning</span>', app.get_password_warning(), "Proceed", function(result) {
					if (result) $P().doResetPassword('force');
				} );
				return;
			} // insecure password
			
			app.showProgress(1.0, _t('login.resetting_password'));
			
			app.api.post( 'user/reset_password', {
				username: username,
				key: recovery_key,
				new_password: new_password
			}, 
			function(resp, tx) {
				Debug.trace("User password was reset: " + username);
				
				app.hideProgress();
				app.setPref('username', username);
				
				Nav.go( 'Login', true );
				
				setTimeout( function() {
					app.showMessage('success', _t('login.your_password_was_reset_successfully'));
				}, 100 );
			} ); // post
		}
	},
	
	onDeactivate: function() {
		// called when page is deactivated
		this.div.html( '' );
		return true;
	}
	
} );
